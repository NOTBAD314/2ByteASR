"""Disk-backed multi-resolution waveform cache for long Studio timelines."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from collections import OrderedDict
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping

import numpy as np

from .studio_project import waveform_cache_root
from .processes import popen_hidden_subprocess, run_hidden_subprocess


WAVEFORM_SCHEMA_VERSION = 1
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 256
LOD_FACTOR = 4
MAX_LOD_LEVELS = 8


class WaveformGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WaveformLevel:
    level: int
    frames: int
    milliseconds_per_frame: float
    file: str


@dataclass(frozen=True)
class WaveformMetadata:
    schema_version: int
    source_path: str
    source_size: int
    source_mtime_ns: int
    sample_rate: int
    window_samples: int
    duration_ms: int
    levels: tuple[WaveformLevel, ...]
    source_start_ms: float = 0.0
    stream_start_ms: float = 0.0
    sample_timeline_origin_ms: float = 0.0
    coverage_end_ms: int = 0
    incomplete: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> "WaveformMetadata":
        if int(payload.get("schema_version", 0)) != WAVEFORM_SCHEMA_VERSION:
            raise WaveformGenerationError("unsupported waveform cache schema")
        return cls(
            schema_version=WAVEFORM_SCHEMA_VERSION,
            source_path=str(payload["source_path"]),
            source_size=int(payload["source_size"]),
            source_mtime_ns=int(payload["source_mtime_ns"]),
            sample_rate=int(payload["sample_rate"]),
            window_samples=int(payload["window_samples"]),
            duration_ms=int(payload["duration_ms"]),
            levels=tuple(WaveformLevel(**item) for item in payload["levels"]),
            source_start_ms=float(payload.get("source_start_ms", 0.0) or 0.0),
            stream_start_ms=float(payload.get("stream_start_ms", payload.get("audio_start_ms", 0.0)) or 0.0),
            sample_timeline_origin_ms=float(payload.get("sample_timeline_origin_ms", payload.get("stream_start_ms", 0.0)) or 0.0),
            coverage_end_ms=int(payload.get("coverage_end_ms", payload.get("duration_ms", 0)) or 0),
            incomplete=bool(payload.get("incomplete", False)),
        )

    def to_dict(self) -> dict:
        payload = {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_size": self.source_size,
            "source_mtime_ns": self.source_mtime_ns,
            "sample_rate": self.sample_rate,
            "window_samples": self.window_samples,
            "duration_ms": self.duration_ms,
            "source_start_ms": self.source_start_ms,
            "stream_start_ms": self.stream_start_ms,
            "sample_timeline_origin_ms": self.sample_timeline_origin_ms,
            "coverage_end_ms": self.coverage_end_ms,
            "levels": [level.__dict__ for level in self.levels],
        }
        if self.incomplete:
            payload["incomplete"] = True
        return payload


def media_cache_key(media_path: str | os.PathLike[str]) -> str:
    path = Path(media_path).resolve()
    stat = path.stat()
    identity = f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def clip_waveform_cache_key(
    asset_fingerprint: str,
    audio_stream: int,
    source_in_ms: int,
    source_out_ms: int,
) -> str:
    """Stable per-clip identity layered over the source-level waveform cache."""

    identity = "|".join((
        str(asset_fingerprint or "missing-fingerprint"),
        str(max(0, int(audio_stream))),
        str(max(0, int(source_in_ms))),
        str(max(0, int(source_out_ms))),
    ))
    return hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:32]


def _write_metadata(path: Path, metadata: WaveformMetadata) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".metadata.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(metadata.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass


def _reduce_level(source_path: Path, source_frames: int, target_path: Path) -> int:
    source = np.memmap(source_path, dtype=np.float32, mode="r", shape=(source_frames, 2))
    target_frames = (source_frames + LOD_FACTOR - 1) // LOD_FACTOR
    target = np.memmap(target_path, dtype=np.float32, mode="w+", shape=(target_frames, 2))
    chunk_target_frames = 65_536
    for target_start in range(0, target_frames, chunk_target_frames):
        target_end = min(target_frames, target_start + chunk_target_frames)
        source_start = target_start * LOD_FACTOR
        source_end = min(source_frames, target_end * LOD_FACTOR)
        block = np.asarray(source[source_start:source_end])
        pad = (-len(block)) % LOD_FACTOR
        if pad:
            block = np.pad(block, ((0, pad), (0, 0)), mode="edge")
        grouped = block.reshape(-1, LOD_FACTOR, 2)
        target[target_start:target_end, 0] = grouped[:, :, 0].min(axis=1)
        target[target_start:target_end, 1] = grouped[:, :, 1].max(axis=1)
    target.flush()
    del target
    del source
    return target_frames


def build_lod_pyramid(
    cache_dir: str | os.PathLike[str],
    level0_frames: int,
    *,
    milliseconds_per_frame: float,
    max_levels: int = MAX_LOD_LEVELS,
) -> tuple[WaveformLevel, ...]:
    root = Path(cache_dir)
    levels = [
        WaveformLevel(0, int(level0_frames), float(milliseconds_per_frame), "lod0.f32")
    ]
    source_frames = int(level0_frames)
    for level_number in range(1, max(1, int(max_levels))):
        if source_frames <= 1:
            break
        target_path = root / f"lod{level_number}.f32"
        source_frames = _reduce_level(
            root / levels[-1].file, source_frames, target_path
        )
        levels.append(
            WaveformLevel(
                level_number,
                source_frames,
                milliseconds_per_frame * (LOD_FACTOR ** level_number),
                target_path.name,
            )
        )
    return tuple(levels)


class _LivePyramid:
    """Append-only LOD pyramid fed by the level-0 bucket stream.

    Keeps every level file on disk in a state where the frames declared in the
    last metadata snapshot are complete, so readers can mmap a growing cache
    at any publish tick. Resume restores the un-reduced tail rows of each
    level from disk instead of trusting in-memory state.
    """

    def __init__(
        self,
        root: Path,
        milliseconds_per_frame: float,
        *,
        resume_levels: tuple[WaveformLevel, ...] | None = None,
    ) -> None:
        self.root = root
        self.milliseconds_per_frame = float(milliseconds_per_frame)
        self.files: list[object] = []
        self.frames: list[int] = []
        self.carry: list[np.ndarray] = []
        resume_levels = resume_levels or ()
        for index, level in enumerate(
            level for level in resume_levels if level.file.startswith("lod")
        ):
            if level.level != index:
                break
            path = root / level.file
            expected = int(level.frames) * 2 * 4
            if path.stat().st_size > expected:
                with path.open("r+b") as handle:
                    handle.truncate(expected)
            handle = path.open("r+b")
            handle.seek(0, os.SEEK_END)
            self.files.append(handle)
            self.frames.append(int(level.frames))
            self.carry.append(np.empty((0, 2), dtype=np.float32))
        if not self.files:
            handle = (root / "lod0.f32").open("wb")
            self.files.append(handle)
            self.frames.append(0)
            self.carry.append(np.empty((0, 2), dtype=np.float32))
        # Rebuild the un-reduced tail of each level from the level below so a
        # resumed run does not leave permanent holes at the resume boundary.
        for index in range(1, len(self.files)):
            remainder = self.frames[index - 1] - self.frames[index] * LOD_FACTOR
            if remainder <= 0 or self.frames[index - 1] <= 0:
                continue
            below = np.memmap(
                root / f"lod{index - 1}.f32", dtype=np.float32, mode="r",
                shape=(self.frames[index - 1], 2),
            )
            self.carry[index] = np.asarray(below[self.frames[index - 1] - remainder:]).copy()
            del below

    def _ensure_level(self, index: int) -> None:
        while len(self.files) <= index:
            self.files.append((self.root / f"lod{len(self.files)}.f32").open("wb"))
            self.frames.append(0)
            self.carry.append(np.empty((0, 2), dtype=np.float32))

    def extend(self, pairs: np.ndarray) -> None:
        self._ensure_level(0)
        if len(pairs):
            self.files[0].write(np.ascontiguousarray(pairs, dtype=np.float32).tobytes())
            self.frames[0] += len(pairs)
        current = pairs
        level = 1
        while level < MAX_LOD_LEVELS and len(current):
            if self.frames[level - 1] <= 1:
                break
            self._ensure_level(level)
            combined = current if not len(self.carry[level]) else np.concatenate((self.carry[level], current))
            groups = len(combined) // LOD_FACTOR
            if groups == 0:
                self.carry[level] = combined
                break
            reshaped = combined[: groups * LOD_FACTOR].reshape(-1, LOD_FACTOR, 2)
            parent = np.column_stack((
                reshaped[:, :, 0].min(axis=1),
                reshaped[:, :, 1].max(axis=1),
            )).astype(np.float32)
            self.carry[level] = combined[groups * LOD_FACTOR:]
            self.files[level].write(parent.tobytes())
            self.frames[level] += groups
            current = parent
            level += 1

    def finish(self) -> None:
        """Edge-pad the final partial group of every level (matches build_lod_pyramid)."""
        for level in range(1, len(self.files)):
            tail = self.carry[level]
            if not len(tail):
                continue
            pad = (-len(tail)) % LOD_FACTOR
            if pad:
                tail = np.pad(tail, ((0, pad), (0, 0)), mode="edge")
            reshaped = tail.reshape(-1, LOD_FACTOR, 2)
            parent = np.column_stack((
                reshaped[:, :, 0].min(axis=1),
                reshaped[:, :, 1].max(axis=1),
            )).astype(np.float32)
            self.files[level].write(parent.tobytes())
            self.frames[level] += len(parent)
            self.carry[level] = np.empty((0, 2), dtype=np.float32)

    def flush(self) -> None:
        for handle in self.files:
            handle.flush()

    def close(self) -> None:
        for handle in self.files:
            try:
                handle.flush()
            except OSError:
                pass
            try:
                handle.close()
            except OSError:
                pass

    def levels(self, outline: WaveformLevel | None = None) -> tuple[WaveformLevel, ...]:
        result = tuple(
            WaveformLevel(
                index,
                self.frames[index],
                self.milliseconds_per_frame * (LOD_FACTOR ** index),
                f"lod{index}.f32",
            )
            for index in range(len(self.files))
            if self.frames[index] > 0
        )
        if outline is not None:
            result = result + (outline,)
        return result


def generate_outline_from_media(
    source_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    *,
    duration_ms: int,
    cancelled: Callable[[], bool] | None = None,
    sample_rate: int = 2_000,
    window_seconds: float = 0.5,
    max_windows: int = 96,
    min_windows: int = 8,
) -> np.ndarray | None:
    """Whole-duration coarse silhouette via bounded strided sampling.

    One ffmpeg process, one small seek per window. Only called on optimized
    (indexed) media — random access on the original FLV is exactly what this
    avoids. Returns ``(N, 2)`` float32 pairs or ``None`` on any failure.
    """
    duration_s = max(0.0, float(duration_ms) / 1000.0)
    if duration_s <= 10.0:
        return None
    try:
        ffmpeg = Path(ffmpeg_path)
        source = Path(source_path)
        if not ffmpeg.is_file() or not source.is_file():
            return None
        windows = int(max(min_windows, min(max_windows, duration_s // 30)))
        step = max(window_seconds + 0.5, (duration_s - window_seconds) / windows)
        starts = [min(max(0.0, index * step), max(0.0, duration_s - window_seconds))
                  for index in range(windows)]
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
        for start in starts:
            command += ["-ss", f"{start:.3f}", "-t", f"{window_seconds:.3f}", "-i", str(source)]
        command += [
            "-filter_complex", f"concat=n={len(starts)}:v=0:a=1[outa]",
            "-map", "[outa]", "-vn", "-ac", "1",
            "-ar", str(int(sample_rate)), "-f", "s16le", "pipe:1",
        ]
        result = run_hidden_subprocess(
            [str(part) for part in command],
            purpose="waveform outline sampling",
            capture_output=True,
            timeout=120,
            check=False,
        )
        if int(result.returncode) != 0:
            return None
        pcm = np.frombuffer(result.stdout, dtype="<i2")
        per_window = int(round(window_seconds * sample_rate))
        expected = per_window * windows
        if len(pcm) < expected * 0.8:
            return None
        usable = min(len(pcm), expected)
        pcm = pcm[:usable - usable % per_window].reshape(windows if usable == expected else -1, per_window)
        pairs = np.column_stack((
            (pcm.min(axis=1).astype(np.float32) / 32768.0),
            (pcm.max(axis=1).astype(np.float32) / 32768.0),
        ))
        return pairs.reshape(-1, 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def append_outline_level(
    cache_dir: str | os.PathLike[str],
    pairs: np.ndarray,
    *,
    ms_per_frame: float,
) -> WaveformLevel | None:
    """Attach (or replace) the whole-duration outline level of an existing cache."""
    root = Path(cache_dir)
    metadata_path = root / "metadata.json"
    try:
        metadata = WaveformMetadata.from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, KeyError, TypeError, WaveformGenerationError):
        return None
    if not len(pairs):
        return None
    data = np.ascontiguousarray(pairs, dtype=np.float32)
    temporary = root / ".outline.tmp.f32"
    temporary.write_bytes(data.tobytes())
    os.replace(temporary, root / "outline.f32")
    existing = [level for level in metadata.levels if level.file != "outline.f32"]
    outline = WaveformLevel(len(existing), int(len(data)), float(ms_per_frame), "outline.f32")
    updated = WaveformMetadata(
        schema_version=metadata.schema_version,
        source_path=metadata.source_path,
        source_size=metadata.source_size,
        source_mtime_ns=metadata.source_mtime_ns,
        sample_rate=metadata.sample_rate,
        window_samples=metadata.window_samples,
        duration_ms=metadata.duration_ms,
        levels=tuple(existing) + (outline,),
        source_start_ms=metadata.source_start_ms,
        stream_start_ms=metadata.stream_start_ms,
        sample_timeline_origin_ms=metadata.sample_timeline_origin_ms,
        coverage_end_ms=metadata.coverage_end_ms,
        incomplete=metadata.incomplete,
    )
    _write_metadata(metadata_path, updated)
    return outline


def generate_waveform_cache_incremental(
    media_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    *,
    cache_root: str | os.PathLike[str] | None = None,
    cancelled: Callable[[], bool] | None = None,
    time_mapping: Mapping[str, object] | None = None,
    decode_path: str | os.PathLike[str] | None = None,
    outline_pairs: np.ndarray | None = None,
    outline_ms_per_frame: float = 0.0,
    min_coverage_ms: int = 0,
    snapshot_interval_ms: float = 1500.0,
    snapshot_min_wall_ms: float = 250.0,
    on_snapshot: Callable[[Path, int], None] | None = None,
) -> Path:
    """Full-resolution waveform with incremental, resumable publishing.

    Writes directly into the final cache directory (no staging rename: Windows
    cannot rename a directory out from under open memmap readers). Every
    publish tick atomically replaces ``metadata.json`` with growing frame
    counts and ``coverage_end_ms``; readers only touch declared frames.
    """
    media = Path(media_path).resolve()
    ffmpeg = Path(ffmpeg_path).resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    if not ffmpeg.is_file():
        raise FileNotFoundError(ffmpeg)
    root = Path(cache_root) if cache_root else waveform_cache_root()
    target = root / media_cache_key(media)
    metadata_path = target / "metadata.json"
    stat = media.stat()

    pyramid: _LivePyramid | None = None
    try:
        resume_levels: tuple[WaveformLevel, ...] | None = None
        base_coverage_ms = 0.0
        if metadata_path.is_file():
            try:
                existing = WaveformMetadata.from_dict(
                    json.loads(metadata_path.read_text(encoding="utf-8"))
                )
                identity_ok = (
                    existing.source_size == stat.st_size
                    and existing.source_mtime_ns == stat.st_mtime_ns
                    and existing.sample_rate == SAMPLE_RATE
                    and existing.window_samples == WINDOW_SAMPLES
                    and str(Path(existing.source_path).resolve()) == str(media)
                )
                if identity_ok and not existing.incomplete:
                    return target
                if (
                    identity_ok
                    and existing.incomplete
                    and decode_path is not None
                    and Path(decode_path).resolve() != media
                ):
                    resume_levels = tuple(
                        level for level in existing.levels if level.file.startswith("lod")
                    )
                    base_coverage_ms = float(existing.coverage_end_ms or 0.0)
                else:
                    shutil.rmtree(target, ignore_errors=True)
            except (OSError, ValueError, KeyError, TypeError, WaveformGenerationError):
                shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        outline: WaveformLevel | None = None
        if outline_pairs is not None and len(outline_pairs) and outline_ms_per_frame > 0.0:
            data = np.ascontiguousarray(outline_pairs, dtype=np.float32)
            temporary = target / ".outline.tmp.f32"
            temporary.write_bytes(data.tobytes())
            os.replace(temporary, target / "outline.f32")
            outline = WaveformLevel(
                MAX_LOD_LEVELS, int(len(data)), float(outline_ms_per_frame), "outline.f32"
            )

        milliseconds_per_frame = WINDOW_SAMPLES * 1000.0 / SAMPLE_RATE
        pyramid = _LivePyramid(target, milliseconds_per_frame, resume_levels=resume_levels)
        start_seconds = base_coverage_ms / 1000.0

        last_publish_coverage = base_coverage_ms
        last_publish_time = perf_counter()

        def on_pairs(pairs: np.ndarray) -> None:
            nonlocal last_publish_coverage, last_publish_time
            if cancelled and cancelled():
                raise InterruptedError("waveform generation cancelled")
            pyramid.extend(pairs)
            coverage_ms = pyramid.frames[0] * milliseconds_per_frame
            now = perf_counter()
            due = (
                coverage_ms >= min_coverage_ms
                and coverage_ms > last_publish_coverage + snapshot_interval_ms
                and (now - last_publish_time) * 1000.0 >= snapshot_min_wall_ms
            )
            if due:
                _publish_snapshot(
                    pyramid, metadata_path, media, stat, target,
                    coverage_ms, time_mapping, outline, incomplete=True,
                )
                if on_snapshot is not None:
                    on_snapshot(target, int(coverage_ms))
                last_publish_coverage = coverage_ms
                last_publish_time = now

        _decode_audio_buckets(
            Path(decode_path) if decode_path else media,
            ffmpeg,
            sample_rate=SAMPLE_RATE,
            window_samples=WINDOW_SAMPLES,
            start_seconds=start_seconds,
            cancelled=cancelled,
            on_pairs=on_pairs,
        )
        pyramid.finish()
        coverage_ms = pyramid.frames[0] * milliseconds_per_frame
        _publish_snapshot(
            pyramid, metadata_path, media, stat, target,
            coverage_ms, time_mapping, outline, incomplete=False,
        )
        if on_snapshot is not None:
            on_snapshot(target, int(coverage_ms))
        return target
    finally:
        if pyramid is not None:
            pyramid.close()


def _publish_snapshot(
    pyramid: _LivePyramid,
    metadata_path: Path,
    media: Path,
    stat: os.stat_result,
    target: Path,
    coverage_ms: float,
    time_mapping: Mapping[str, object] | None,
    outline: WaveformLevel | None,
    *,
    incomplete: bool,
) -> None:
    pyramid.flush()
    metadata = WaveformMetadata(
        schema_version=WAVEFORM_SCHEMA_VERSION,
        source_path=str(media),
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        sample_rate=SAMPLE_RATE,
        window_samples=WINDOW_SAMPLES,
        duration_ms=int(round(coverage_ms)),
        levels=pyramid.levels(outline=outline),
        source_start_ms=float((time_mapping or {}).get("source_start_ms", 0.0) or 0.0),
        stream_start_ms=float((time_mapping or {}).get("audio_start_ms", (time_mapping or {}).get("stream_start_ms", 0.0)) or 0.0),
        sample_timeline_origin_ms=float((time_mapping or {}).get("sample_timeline_origin_ms", (time_mapping or {}).get("audio_start_ms", 0.0)) or 0.0),
        coverage_end_ms=int(round(coverage_ms)),
        incomplete=incomplete,
    )
    if not metadata.levels:
        raise WaveformGenerationError("media contains no decodable audio waveform")
    _write_metadata(metadata_path, metadata)


def _decode_audio_buckets(
    media_path: Path,
    ffmpeg_path: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
    window_samples: int = WINDOW_SAMPLES,
    start_seconds: float = 0.0,
    max_duration_seconds: float | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_pairs: Callable[[np.ndarray], None] | None = None,
) -> tuple[int, int]:
    """Sequentially decode mono PCM and reduce it into min/max buckets.

    ``on_pairs`` receives float32 ``(N, 2)`` min/max bucket arrays as they
    complete — the hook that makes progressive waveform publishing possible.
    """
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if float(start_seconds) > 0.0:
        command.extend(["-ss", f"{max(0.0, float(start_seconds)):.3f}"])
    command.extend([
        "-i",
        str(media_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(max(1, int(sample_rate))),
        "-f",
        "s16le",
        "pipe:1",
    ])
    if max_duration_seconds is not None:
        # ``-t`` belongs after the input for decoded duration limiting.
        command[command.index("-vn"):command.index("-vn")] = ["-t", f"{max(0.01, float(max_duration_seconds)):.3f}"]
    process = popen_hidden_subprocess(
        command,
        purpose="ffmpeg waveform",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pending = np.empty(0, dtype=np.int16)
    frames = 0
    samples = 0
    chunks: queue.Queue[bytes] = queue.Queue()
    reader_done = threading.Event()
    reader_errors: list[BaseException] = []

    def read_stdout() -> None:
        try:
            while process.stdout:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                chunks.put(chunk)
        except BaseException as exc:
            reader_errors.append(exc)
        finally:
            reader_done.set()

    reader = threading.Thread(
        target=read_stdout,
        daemon=True,
        name="waveform-ffmpeg-reader",
    )
    reader.start()
    try:
        while True:
            if cancelled and cancelled():
                raise InterruptedError("waveform generation cancelled")
            try:
                chunk = chunks.get(timeout=0.05)
            except queue.Empty:
                if reader_done.is_set():
                    break
                continue
            decoded = np.frombuffer(chunk, dtype="<i2")
            samples += len(decoded)
            if pending.size:
                decoded = np.concatenate((pending, decoded))
            complete = (len(decoded) // window_samples) * window_samples
            if complete:
                grouped = decoded[:complete].reshape(-1, window_samples)
                pairs = np.column_stack((grouped.min(axis=1), grouped.max(axis=1)))
                pairs = pairs.astype(np.float32) / 32768.0
                if on_pairs is not None:
                    on_pairs(pairs)
                frames += len(pairs)
            pending = decoded[complete:].copy()
        if reader_errors:
            raise reader_errors[0]
        if pending.size:
            pairs = (np.array([[pending.min(), pending.max()]], dtype=np.float32) / 32768.0)
            if on_pairs is not None:
                on_pairs(pairs)
            frames += 1
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code != 0:
            raise WaveformGenerationError(
                f"ffmpeg waveform decode failed ({return_code}): {stderr[-1200:]}"
            )
    except BaseException:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        reader.join(timeout=1.0)
        raise
    reader.join(timeout=1.0)
    return frames, samples


def _decode_level0(
    media_path: Path,
    ffmpeg_path: Path,
    output_path: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    sample_rate: int = SAMPLE_RATE,
    window_samples: int = WINDOW_SAMPLES,
    start_seconds: float = 0.0,
    max_duration_seconds: float | None = None,
) -> tuple[int, int]:
    frames = 0
    samples = 0
    with output_path.open("wb") as output:
        def write_pairs(pairs: np.ndarray) -> None:
            output.write(pairs.tobytes())

        frames, samples = _decode_audio_buckets(
            media_path,
            ffmpeg_path,
            cancelled=cancelled,
            sample_rate=sample_rate,
            window_samples=window_samples,
            start_seconds=start_seconds,
            max_duration_seconds=max_duration_seconds,
            on_pairs=write_pairs,
        )
    return frames, samples


def generate_waveform_cache(
    media_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    *,
    cache_root: str | os.PathLike[str] | None = None,
    cancelled: Callable[[], bool] | None = None,
    time_mapping: Mapping[str, object] | None = None,
) -> Path:
    return _generate_waveform_variant(
        media_path,
        ffmpeg_path,
        cache_root=cache_root,
        cancelled=cancelled,
        sample_rate=SAMPLE_RATE,
        window_samples=WINDOW_SAMPLES,
        key_suffix="",
        time_mapping=time_mapping,
    )


def _generate_waveform_variant(
    media_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    *,
    cache_root: str | os.PathLike[str] | None,
    cancelled: Callable[[], bool] | None,
    sample_rate: int,
    window_samples: int,
    key_suffix: str,
    time_mapping: Mapping[str, object] | None = None,
    start_seconds: float = 0.0,
    max_duration_seconds: float | None = None,
) -> Path:
    media = Path(media_path).resolve()
    ffmpeg = Path(ffmpeg_path).resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    if not ffmpeg.is_file():
        raise FileNotFoundError(ffmpeg)
    root = Path(cache_root) if cache_root else waveform_cache_root()
    target = root / f"{media_cache_key(media)}{key_suffix}"
    metadata_path = target / "metadata.json"
    if metadata_path.is_file():
        try:
            metadata = WaveformMetadata.from_dict(
                json.loads(metadata_path.read_text(encoding="utf-8"))
            )
            stat = media.stat()
            if (
                metadata.source_size == stat.st_size
                and metadata.source_mtime_ns == stat.st_mtime_ns
                and metadata.sample_rate == int(sample_rate)
                and metadata.window_samples == int(window_samples)
                and all(key in json.loads(metadata_path.read_text(encoding="utf-8"))
                        for key in ("source_start_ms", "stream_start_ms", "sample_timeline_origin_ms"))
                and all((target / item.file).is_file() for item in metadata.levels)
            ):
                return target
        except (OSError, ValueError, KeyError, TypeError, WaveformGenerationError):
            pass

    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{target.name}.{uuid.uuid4().hex}.new"
    staging.mkdir(parents=True)
    try:
        frames, samples = _decode_level0(
            media,
            ffmpeg,
            staging / "lod0.f32",
            cancelled=cancelled,
            sample_rate=sample_rate,
            window_samples=window_samples,
            start_seconds=start_seconds,
            max_duration_seconds=max_duration_seconds,
        )
        if frames <= 0:
            raise WaveformGenerationError("media contains no decodable audio waveform")
        milliseconds_per_frame = window_samples * 1000.0 / sample_rate
        levels = build_lod_pyramid(
            staging, frames, milliseconds_per_frame=milliseconds_per_frame
        )
        stat = media.stat()
        metadata = WaveformMetadata(
            schema_version=WAVEFORM_SCHEMA_VERSION,
            source_path=str(media),
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            sample_rate=sample_rate,
            window_samples=window_samples,
            duration_ms=round(samples * 1000 / sample_rate),
            levels=levels,
            source_start_ms=float((time_mapping or {}).get("source_start_ms", 0.0) or 0.0),
            stream_start_ms=float((time_mapping or {}).get("audio_start_ms", (time_mapping or {}).get("stream_start_ms", 0.0)) or 0.0),
            sample_timeline_origin_ms=float((time_mapping or {}).get("sample_timeline_origin_ms", (time_mapping or {}).get("audio_start_ms", 0.0)) or 0.0),
            coverage_end_ms=round(float(start_seconds) * 1000.0 + samples * 1000.0 / sample_rate),
        )
        _write_metadata(staging / "metadata.json", metadata)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def generate_progressive_waveform_cache(
    media_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    *,
    cache_root: str | os.PathLike[str] | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_ready: Callable[[str, Path], None] | None = None,
    before_refine: Callable[[], bool] | None = None,
    time_mapping: Mapping[str, object] | None = None,
    decode_source_resolver: Callable[[], str | os.PathLike[str] | None] | None = None,
    duration_ms: int | None = None,
    log: Callable[[str, Mapping[str, object]], None] | None = None,
) -> Path:
    """Coarse head -> whole-duration outline -> incrementally published full cache.

    ``decode_source_resolver`` may block (e.g. waiting for the FLV remux); it
    returns the path the full decode should read, or ``None``/the original.
    """
    media = Path(media_path).resolve()
    root = Path(cache_root) if cache_root else waveform_cache_root()
    final_path = root / media_cache_key(media)
    trace = log or (lambda _event, _fields: None)
    started = perf_counter()

    # 1) A previously completed full cache wins immediately.
    if final_path.joinpath("metadata.json").is_file():
        try:
            warm = generate_waveform_cache(
                media, ffmpeg_path, cache_root=root, cancelled=cancelled,
                time_mapping=time_mapping,
            )
            trace("WAVEFORM", {
                "cache_hit": True, "stage": "full",
                "elapsed_ms": round((perf_counter() - started) * 1000.0, 1),
            })
            if on_ready:
                on_ready("full", warm)
            return warm
        except (OSError, ValueError, KeyError, TypeError, WaveformGenerationError):
            pass

    # 2) Coarse head straight from the original: first visible waveform.
    coarse_started = perf_counter()
    coarse = _generate_waveform_variant(
        media,
        ffmpeg_path,
        cache_root=root,
        cancelled=cancelled,
        sample_rate=2_000,
        window_samples=1_024,
        key_suffix="-coarse-v1",
        time_mapping=time_mapping,
        start_seconds=0.0,
        max_duration_seconds=120.0,
    )
    if on_ready:
        on_ready("coarse", coarse)
    trace("WAVEFORM", {
        "stage": "coarse", "first_waveform_ms": round((perf_counter() - coarse_started) * 1000.0, 1),
    })
    if cancelled and cancelled():
        raise InterruptedError("waveform generation cancelled")
    if before_refine is not None and not before_refine():
        raise InterruptedError("waveform refinement cancelled")

    # 3) Resolve the decode source (usually: wait for the lossless remux).
    decode_path: Path | None = None
    if decode_source_resolver is not None:
        resolved = decode_source_resolver()
        if cancelled and cancelled():
            raise InterruptedError("waveform generation cancelled")
        if resolved:
            candidate = Path(resolved).resolve()
            if candidate.is_file() and candidate != media:
                decode_path = candidate
    trace("WAVEFORM", {
        "stage": "decode_source",
        "decoder": str(decode_path) if decode_path else "original",
    })

    # 4) Whole-duration outline silhouette — only on an indexed source, where
    #    the bounded strided seeks are cheap.
    outline_pairs: np.ndarray | None = None
    outline_ms_per_frame = 0.0
    known_duration_ms = int(duration_ms or 0)
    if decode_path is not None and known_duration_ms > 10_000:
        outline_started = perf_counter()
        pairs = generate_outline_from_media(
            decode_path, ffmpeg_path, duration_ms=known_duration_ms, cancelled=cancelled,
        )
        if pairs is not None and len(pairs):
            outline_pairs = pairs
            outline_ms_per_frame = float(known_duration_ms) / float(len(pairs))
            if append_outline_level(coarse, pairs, ms_per_frame=outline_ms_per_frame) is not None:
                if on_ready:
                    on_ready("coarse", coarse)
            trace("WAVEFORM", {
                "stage": "outline", "outline_ms": round((perf_counter() - outline_started) * 1000.0, 1),
                "outline_points": int(len(pairs)),
            })

    # 5) Full decode with incremental snapshots.
    min_coverage_ms = 0
    try:
        coarse_metadata = WaveformMetadata.from_dict(
            json.loads((coarse / "metadata.json").read_text(encoding="utf-8"))
        )
        min_coverage_ms = max(0, int(coarse_metadata.coverage_end_ms or 0))
    except (OSError, ValueError, KeyError, TypeError, WaveformGenerationError):
        pass
    first_partial_ms: float | None = None
    snapshot_count = 0

    def on_snapshot(path: Path, coverage_ms: int) -> None:
        nonlocal first_partial_ms, snapshot_count
        snapshot_count += 1
        if first_partial_ms is None:
            first_partial_ms = round((perf_counter() - started) * 1000.0, 1)
            trace("WAVEFORM", {"stage": "first_partial", "since_start_ms": first_partial_ms,
                               "coverage_ms": int(coverage_ms)})
        elif snapshot_count % 8 == 0:
            trace("WAVEFORM", {"stage": "partial", "coverage_ms": int(coverage_ms)})
        if on_ready:
            on_ready("partial", path)

    final = generate_waveform_cache_incremental(
        media,
        ffmpeg_path,
        cache_root=root,
        cancelled=cancelled,
        time_mapping=time_mapping,
        decode_path=str(decode_path) if decode_path is not None else None,
        outline_pairs=outline_pairs,
        outline_ms_per_frame=outline_ms_per_frame,
        min_coverage_ms=min_coverage_ms,
        on_snapshot=on_snapshot,
    )
    if on_ready:
        on_ready("full", final)
    trace("WAVEFORM", {
        "stage": "full_complete", "full_complete_ms": round((perf_counter() - started) * 1000.0, 1),
        "cache_hit": False,
    })
    return final


class WaveformCache:
    def __init__(self, cache_dir: str | os.PathLike[str]) -> None:
        self.root = Path(cache_dir)
        self.metadata = WaveformMetadata.from_dict(
            json.loads((self.root / "metadata.json").read_text(encoding="utf-8"))
        )
        self._maps = {}
        self._tiles = OrderedDict()
        self.stats = {'hits':0, 'misses':0, 'points':0}

    def choose_level(self, start_ms: int, end_ms: int, pixel_width: int) -> WaveformLevel:
        span_ms = max(1, int(end_ms) - int(start_ms))
        desired_ms_per_pixel = span_ms / max(1, int(pixel_width))
        candidates = [
            level
            for level in self.metadata.levels
            if level.milliseconds_per_frame <= desired_ms_per_pixel * 2.0
        ]
        # While the cache is still filling, a fine level may not reach the
        # requested window yet. Fall back to coarser levels that do cover it
        # (typically the whole-duration outline) instead of drawing nothing.
        if not candidates:
            return self.metadata.levels[0]
        origin_ms = float(self.metadata.sample_timeline_origin_ms or 0.0)
        # Requests may carry the *container* duration while the decoded audio
        # stream ends seconds earlier (FLV tails, AAC priming). On a COMPLETE
        # cache, clamp the request to the audio coverage and allow one bucket
        # of rounding slack: with the old flat 50ms cap every whole-clip view
        # was permanently demoted to the sparse outline level (one 0.5s sample
        # per ~56s) and looked flat. While the cache is still filling, keep
        # the raw request and the tight cap so genuinely-uncovered tails defer
        # to the whole-duration outline preview (design behavior).
        finest = min(self.metadata.levels, key=lambda item: item.milliseconds_per_frame)
        audio_end_ms = origin_ms + finest.frames * finest.milliseconds_per_frame
        complete = not self.metadata.incomplete
        request_end_ms = min(float(end_ms), audio_end_ms + finest.milliseconds_per_frame) if complete else float(end_ms)

        def covers(level: WaveformLevel, end_value: float, bucket_slack: bool) -> bool:
            slack = level.milliseconds_per_frame if bucket_slack else min(level.milliseconds_per_frame, 50.0)
            covered_ms = origin_ms + level.frames * level.milliseconds_per_frame
            return covered_ms >= end_value - slack

        for level in reversed(candidates):
            if covers(level, request_end_ms, complete):
                return level
        for level in sorted(
            self.metadata.levels, key=lambda item: item.milliseconds_per_frame, reverse=True
        ):
            if covers(level, float(end_ms), False):
                return level
        return candidates[-1]

    def read_window(
        self, start_ms: int, end_ms: int, pixel_width: int
    ) -> tuple[WaveformLevel, np.ndarray]:
        level = self.choose_level(start_ms, end_ms, pixel_width)
        # The decoded sample at index zero is not necessarily project time
        # zero.  FLV audio commonly starts with a non-zero stream PTS; use the
        # persisted sample origin so waveform clicks address the same source
        # time as live playback.
        origin_ms = float(self.metadata.sample_timeline_origin_ms or 0.0)
        first = max(0, int((float(start_ms) - origin_ms) / level.milliseconds_per_frame))
        last = min(
            level.frames,
            int(np.ceil((float(end_ms) - origin_ms) / level.milliseconds_per_frame)),
        )
        if last <= first:
            return level, np.empty((0, 2), dtype=np.float32)
        mapped = self._maps.get(level.file)
        if mapped is None:
            mapped = self._maps[level.file] = np.memmap(self.root/level.file,
                dtype=np.float32,mode='r',shape=(level.frames,2))
        chunks=[]
        for tile_index in range(first//256,(last-1)//256+1):
            key=(level.file,tile_index)
            tile=self._tiles.get(key)
            if tile is None:
                tile=np.asarray(mapped[tile_index*256:min(level.frames,(tile_index+1)*256)]).copy()
                self._tiles[key]=tile
                self.stats['misses']+=1
                while len(self._tiles)>128:self._tiles.popitem(last=False)
            else:
                self._tiles.move_to_end(key)
                self.stats['hits']+=1
            chunks.append(tile[max(0,first-tile_index*256):min(256,last-tile_index*256)])
        self.stats['points']+=last-first
        return level, np.concatenate(chunks)
