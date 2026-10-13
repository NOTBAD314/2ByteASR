"""Piecewise source-timestamp ↔ audio-content mapping for gappy recordings.

Long livestream FLVs commonly contain recorder dropouts where BOTH streams'
timestamps jump forward together (joint holes). Players that address content by
timestamp (mpv) run through those holes, while continuous decoders (ASR audio
extraction, the PCM windows of the audio engine) squeeze them out — the two
worlds drift apart by the accumulated hole time. :class:`AVSyncMap` restores
one shared clock: the project timeline runs in *audio content* time and mpv
observations/seeks translate at a single boundary.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .processes import popen_hidden_subprocess, run_hidden_subprocess
from .runtime_trace import GLOBAL_STUDIO_TRACE


AV_SYNC_MAP_SCHEMA = 1
GAP_THRESHOLD_SECONDS = 0.5
JOINT_TOLERANCE_SECONDS = 0.35
NEGATIVE_JUMP_SECONDS = 0.05


@dataclass(frozen=True)
class TimestampGap:
    """A forward hole in one stream's timestamps (source-time domain)."""

    start_ms: int
    end_ms: int
    gap_ms: int
    video: bool = False
    audio: bool = False

    @property
    def joint(self) -> bool:
        return self.video and self.audio


@dataclass(frozen=True)
class SyncOverride:
    """Manual correction: shift video by ``offset_ms`` from ``at_ms`` on."""

    at_ms: int
    offset_ms: int


@dataclass
class AVSyncScanResult:
    map: "AVSyncMap"
    status: str  # healthy | warning
    event_count: int
    video_only_gaps: int
    negative_jumps: int
    scanned_packets: int


class AVSyncMap:
    """Maps source timestamps to audio-content time using the audio holes."""

    def __init__(
        self,
        gaps: Iterable[TimestampGap] = (),
        *,
        source_duration_ms: int | None = None,
        overrides: Iterable[SyncOverride] = (),
        stream_holes: Mapping[str, Iterable[tuple[int, int]]] | None = None,
        stream_indices: Mapping[str, int] | None = None,
    ) -> None:
        # The content clock follows AUDIO. Joint holes shift both worlds;
        # video-only holes are reported but never shift the audio clock (the
        # video simply has no frames there and holds — the honest rendering).
        self.gaps: tuple[TimestampGap, ...] = tuple(
            gap for gap in gaps if gap.audio
        )
        self.all_gaps: tuple[TimestampGap, ...] = tuple(gaps)
        # Per-stream hole schedules ((start_ms, end_ms), ...). Hole boundaries
        # differ slightly per stream (video frame vs AAC alignment), so the
        # continuous proxy folds each stream by its own holes.
        holes = dict(stream_holes or {})
        self.video_holes: tuple[tuple[int, int], ...] = tuple(
            (int(a), int(b)) for a, b in holes.get("video", ())
        )
        self.audio_holes: tuple[tuple[int, int], ...] = tuple(
            (int(a), int(b)) for a, b in holes.get("audio", ())
        )
        self.source_duration_ms = int(source_duration_ms or 0)
        # Which file streams the scan classified as video/audio. Maps saved
        # before 2026-10-12 lack it and assumed video=0, audio=1.
        self.stream_indices: dict[str, int] | None = (
            {str(k): int(v) for k, v in stream_indices.items()} if stream_indices else None
        )
        self.overrides: tuple[SyncOverride, ...] = tuple(
            sorted(overrides, key=lambda item: (item.at_ms, item.offset_ms))
        )

    # ------------------------------------------------------------- mapping

    @property
    def total_gap_ms(self) -> int:
        return sum(gap.gap_ms for gap in self.gaps)

    @property
    def content_duration_ms(self) -> int:
        return max(0, self.source_duration_ms - self.total_gap_ms)

    @property
    def is_identity(self) -> bool:
        return not self.gaps and not self.overrides

    def source_to_content_ms(self, source_ms: float) -> float:
        original = float(source_ms)
        offset = 0
        for gap in self.gaps:
            if original >= gap.end_ms:
                offset += gap.gap_ms
            elif original > gap.start_ms:
                # Inside a hole: the nearest existing content is its start.
                return max(0.0, gap.start_ms - offset)
        return max(0.0, original - offset)

    def content_to_source_ms(self, content_ms: float) -> float:
        # Compare against each hole's *content-domain* start (its source start
        # minus the offsets already accumulated before it); comparing a content
        # coordinate against raw source starts mixes domains. A coordinate at
        # the hole boundary maps to the hole's source END — the first real
        # media after the gap.
        original = float(content_ms)
        value = original
        offset_before = 0
        for gap in self.gaps:
            if original >= gap.start_ms - offset_before:
                value += gap.gap_ms
            offset_before += gap.gap_ms
        for override in self.overrides:
            if original >= override.at_ms:
                value += override.offset_ms
        return max(0.0, value)

    def with_overrides(self, overrides: Iterable[SyncOverride]) -> "AVSyncMap":
        return AVSyncMap(
            self.all_gaps,
            source_duration_ms=self.source_duration_ms,
            overrides=overrides,
            stream_holes={"video": self.video_holes, "audio": self.audio_holes},
            stream_indices=self.stream_indices,
        )

    # ---------------------------------------------------------- (de)coding

    def to_dict(self) -> dict:
        return {
            "schema_version": AV_SYNC_MAP_SCHEMA,
            "source_duration_ms": self.source_duration_ms,
            **({"stream_indices": dict(self.stream_indices)} if self.stream_indices else {}),
            "stream_holes": {
                "video": [list(item) for item in self.video_holes],
                "audio": [list(item) for item in self.audio_holes],
            },
            "gaps": [
                {
                    "start_ms": gap.start_ms,
                    "end_ms": gap.end_ms,
                    "gap_ms": gap.gap_ms,
                    "video": gap.video,
                    "audio": gap.audio,
                }
                for gap in self.all_gaps
            ],
            "overrides": [
                {"at_ms": item.at_ms, "offset_ms": item.offset_ms}
                for item in self.overrides
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "AVSyncMap":
        if int(payload.get("schema_version", 0)) != AV_SYNC_MAP_SCHEMA:
            raise ValueError("unsupported av sync map schema")
        gaps = tuple(
            TimestampGap(
                start_ms=int(item["start_ms"]),
                end_ms=int(item["end_ms"]),
                gap_ms=int(item["gap_ms"]),
                video=bool(item.get("video", False)),
                audio=bool(item.get("audio", False)),
            )
            for item in payload.get("gaps", ())
        )
        overrides = tuple(
            SyncOverride(at_ms=int(item["at_ms"]), offset_ms=int(item["offset_ms"]))
            for item in payload.get("overrides", ())
        )
        holes = payload.get("stream_holes") or {}
        return cls(
            gaps,
            source_duration_ms=int(payload.get("source_duration_ms", 0) or 0),
            overrides=overrides,
            stream_indices=payload.get("stream_indices") if isinstance(payload.get("stream_indices"), Mapping) else None,
            stream_holes={
                key: tuple(
                    (int(item[0]), int(item[1]))
                    for item in (holes.get(key) or ())
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                )
                for key in ("video", "audio")
            },
        )

    @classmethod
    def identity(cls) -> "AVSyncMap":
        return cls()


# ------------------------------------------------------------------ scanner


def scan_timestamp_gaps(
    media_path: str | Path,
    ffprobe_path: str | Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[int], None] | None = None,
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    source_duration_ms: int | None = None,
) -> AVSyncScanResult:
    """Stream packet timestamps (no decode) and build the sync map.

    One sequential demux pass over the media — run it on the optimized
    (remuxed) copy, whose index keeps the read sequential and cheap.
    """
    media = Path(media_path)
    ffprobe = Path(ffprobe_path)
    # FLV stream numbering follows the order of the first packets: OBS/RTMP
    # recordings often put audio first. Classify by codec type, never by index.
    video_index, audio_index = probe_av_stream_indices(media, ffprobe)
    command = [
        str(ffprobe), "-v", "error",
        "-show_entries", "packet=stream_index,pts_time,dts_time",
        "-of", "csv=print_section=0", str(media),
    ]
    process = popen_hidden_subprocess(
        command,
        purpose="av sync timestamp scan",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    prev = {video_index: None, audio_index: None}
    video_gaps: list[tuple[float, float]] = []
    audio_gaps: list[tuple[float, float]] = []
    negative_jumps = 0
    packets = 0
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            if cancelled and cancelled():
                raise InterruptedError("av sync scan cancelled")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                stream = int(parts[0])
            except ValueError:
                continue
            stamp = None
            for value in (parts[2], parts[1]):  # prefer dts, fall back to pts
                try:
                    stamp = float(value)
                    break
                except ValueError:
                    continue
            if stamp is None or stream not in prev:
                continue
            packets += 1
            if packets % 200_000 == 0 and on_progress is not None:
                on_progress(packets)
            previous = prev[stream]
            prev[stream] = stamp
            if previous is None:
                continue
            delta = stamp - previous
            if delta < -NEGATIVE_JUMP_SECONDS:
                negative_jumps += 1
                continue
            if delta > gap_threshold_seconds:
                (video_gaps if stream == video_index else audio_gaps).append((previous, stamp))
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass

    # Merge video/audio holes that sit at the same place into joint gaps.
    merged: list[TimestampGap] = []
    used_video = set()
    for a_start, a_end in audio_gaps:
        partner = None
        for index, (v_start, v_end) in enumerate(video_gaps):
            if index in used_video:
                continue
            if abs(v_start - a_start) <= JOINT_TOLERANCE_SECONDS:
                partner = index
                break
        merged.append(
            TimestampGap(
                start_ms=int(a_start * 1000),
                end_ms=int(a_end * 1000),
                gap_ms=int(round((a_end - a_start) * 1000)),
                video=partner is not None,
                audio=True,
            )
        )
        if partner is not None:
            used_video.add(partner)
    video_only = [video_gaps[i] for i in range(len(video_gaps)) if i not in used_video]
    for v_start, v_end in video_only:
        merged.append(
            TimestampGap(
                start_ms=int(v_start * 1000),
                end_ms=int(v_end * 1000),
                gap_ms=int(round((v_end - v_start) * 1000)),
                video=True,
                audio=False,
            )
        )
    merged.sort(key=lambda gap: gap.start_ms)

    duration = int(source_duration_ms or 0)
    if not duration:
        from .media_service import GLOBAL_MEDIA_SERVICE
        try:
            duration = int(GLOBAL_MEDIA_SERVICE.metadata(media).duration_ms)
        except Exception:
            duration = 0

    sync_map = AVSyncMap(
        merged,
        source_duration_ms=duration,
        stream_indices={"video": video_index, "audio": audio_index},
        stream_holes={
            "video": [
                (int(start * 1000), int(end * 1000)) for start, end in video_gaps
            ],
            "audio": [
                (int(start * 1000), int(end * 1000)) for start, end in audio_gaps
            ],
        },
    )
    audio_holes = sum(1 for gap in merged if gap.audio)
    status = "healthy" if not merged and not negative_jumps else "warning"
    result = AVSyncScanResult(
        map=sync_map,
        status=status,
        event_count=len(merged),
        video_only_gaps=len(video_only),
        negative_jumps=negative_jumps,
        scanned_packets=packets,
    )
    GLOBAL_STUDIO_TRACE.emit("AVSyncCheck", {
        "source": str(media),
        "status": status,
        "type": ("joint_step" if audio_holes else
                 "video_gap" if video_only else
                 "unknown" if negative_jumps else "none"),
        "events": len(merged),
        "audio_holes": audio_holes,
        "video_only_gaps": len(video_only),
        "negative_jumps": negative_jumps,
        "total_gap_ms": sync_map.total_gap_ms,
        "first_event_ms": merged[0].start_ms if merged else 0,
        "estimated_offset_after_ms": sync_map.total_gap_ms if merged else 0,
        "packets": packets,
    })
    return result


def probe_av_stream_indices(media_path: str | Path, ffprobe_path: str | Path) -> tuple[int, int]:
    """File indices of the first video and first audio stream (default 0, 1)."""
    try:
        result = run_hidden_subprocess(
            [str(ffprobe_path), "-v", "error", "-show_entries", "stream=index,codec_type",
             "-of", "json", str(media_path)],
            purpose="classify av streams", capture_output=True, timeout=60, check=False)
        streams = json.loads(result.stdout or "{}").get("streams") or []
    except (OSError, ValueError, subprocess.SubprocessError):
        streams = []
    video = next((int(s["index"]) for s in streams if s.get("codec_type") == "video"), 0)
    audio = next((int(s["index"]) for s in streams if s.get("codec_type") == "audio"), 1)
    return video, audio


def load_sync_map(cache_dir: str | Path) -> AVSyncMap | None:
    path = Path(cache_dir) / "sync-map.json"
    if not path.is_file():
        return None
    try:
        return AVSyncMap.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_sync_map(cache_dir: str | Path, sync_map: AVSyncMap) -> Path:
    path = Path(cache_dir) / "sync-map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".sync-map.tmp.json")
    temporary.write_text(
        json.dumps(sync_map.to_dict(), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


__all__ = [
    "AVSyncMap", "AVSyncScanResult", "TimestampGap", "SyncOverride",
    "scan_timestamp_gaps", "load_sync_map", "save_sync_map",
]


# ------------------------------------------------- continuous playback proxy


def _normalize_to_millisecond_mkv(source: Path, target: Path) -> Path:
    probe = run_hidden_subprocess(
        [
            _ffprobe_executable(), "-v", "error",
            "-show_entries", "stream=time_base", "-of", "json", str(source),
        ],
        purpose="probe proxy source time bases",
        capture_output=True, timeout=60, check=False,
    )
    try:
        payload = json.loads(probe.stdout or "{}")
        bases = {s.get("time_base") for s in payload.get("streams", [])}
    except (ValueError, AttributeError, TypeError):
        bases = set()
    if bases and bases <= {"1/1000"}:
        return source
    normalized = target.with_name(f".norm.{target.stem}.{os.getpid()}.mkv")
    from .audio_engine import studio_ffmpeg_path

    result = run_hidden_subprocess(
        [
            str(studio_ffmpeg_path()), "-hide_banner", "-loglevel", "error",
            "-nostdin", "-y", "-i", str(source), "-map", "0", "-c", "copy",
            str(normalized),
        ],
        purpose="normalize proxy source to 1/1000 mkv",
        capture_output=True, timeout=1800, check=False,
    )
    if int(result.returncode) != 0 or not normalized.is_file():
        try:
            normalized.unlink(missing_ok=True)
        except OSError:
            pass
        return source
    return normalized


def _ffprobe_executable() -> Path:
    from .audio_engine import studio_ffmpeg_path

    return studio_ffmpeg_path().with_name(
        "ffprobe.exe" if os.name == "nt" else "ffprobe"
    )


def build_continuous_proxy(
    source_path: str | Path,
    sync_map: "AVSyncMap",
    target_path: str | Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> Path:
    """Packet-remux the optimized copy with joint gaps folded out.

    Stream copy only — no decode, no filters, no genpts: every packet payload
    is byte-identical; only pts/dts are shifted down by the cumulative joint
    gap time. The result is a continuous-timeline mirror of the audio content
    clock that preview consumers (mpv, audio engine, thumbnails) can bind
    with an identity map, so a 1–7 s livestream dropout no longer freezes
    playback for its full wall-clock length.
    """
    import av

    source = Path(source_path)
    target = Path(target_path)
    # §4 time_base 陷阱（2026-09-18 8x 回归根因之一）：optimized MP4 的流
    # time_base 是 1/16000、1/44100 等任意值，PyAV 模板 mux 对非 1/1000
    # 输入的时间戳改写不可靠（时长塌缩 ~5-16x）。先经一次 ffmpeg -c copy
    # 规范成 1/1000 MKV，再走已验证的包级折叠。包数/编解码不变。
    source = _normalize_to_millisecond_mkv(source, target)
    video_schedule = list(sync_map.video_holes) or [
        (gap.start_ms, gap.end_ms) for gap in sync_map.gaps if gap.video
    ]
    audio_schedule = list(sync_map.audio_holes) or [
        (gap.start_ms, gap.end_ms) for gap in sync_map.gaps if gap.audio
    ]
    if not video_schedule and not audio_schedule:
        raise ValueError("continuous proxy requires a sync map with gaps")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.partial.mkv")
    input_container = av.open(str(source))
    try:
        output_container = av.open(str(temporary), "w", format="matroska")
        try:
            stream_map = {}
            from fractions import Fraction

            for stream in input_container.streams:
                out_stream = output_container.add_stream_from_template(stream)
                # 输入已规范化为 1/1000；显式钉住输出流 time_base，
                # 杜绝 muxer 侧任意 time_base 造成的时间戳塌缩。
                try:
                    out_stream.time_base = Fraction(1, 1000)
                except Exception:
                    pass
                stream_map[stream.index] = out_stream
            # Per-stream folding cursors: file order interleaves streams and
            # dropouts leave stray in-hole packets, so a single global cursor
            # can fold a later packet below an earlier one (muxer EINVAL).
            schedules = {}
            for stream in input_container.streams:
                codec_type = str(getattr(stream, "type", "") or "")
                if codec_type == "video":
                    schedules[stream.index] = video_schedule
                elif codec_type == "audio":
                    schedules[stream.index] = audio_schedule
                else:
                    schedules[stream.index] = []
            cursors = {
                stream.index: [0, 0.0, None] for stream in input_container.streams
            }
            packets = 0
            for packet in input_container.demux():
                if cancelled and cancelled():
                    raise InterruptedError("continuous proxy cancelled")
                packets += 1
                if packets % 200_000 == 0 and on_progress is not None:
                    on_progress(packets)
                out_stream = stream_map.get(packet.stream.index)
                if out_stream is None:
                    continue
                if packet.dts is None and packet.pts is None:
                    # Demux flush sentinel at EOF (no payload, no timestamps);
                    # muxing it into matroska fails with EINVAL.
                    continue
                in_base = packet.stream.time_base
                out_base = out_stream.time_base

                def to_ms(value) -> float:
                    return float(value * in_base) * 1000.0

                def from_ms(value_ms: float) -> int:
                    return int(round(value_ms / 1000.0 / float(out_base)))

                # Per-stream shift anchored on DTS; pts/dts deltas survive
                # untouched, in-hole strays clamp to the hole start, and the
                # folded timeline never moves backwards within a stream.
                cursor = cursors[packet.stream.index]
                stream_gaps = schedules.get(packet.stream.index, [])
                anchor_ms = (
                    to_ms(packet.dts) if packet.dts is not None
                    else to_ms(packet.pts) if packet.pts is not None
                    else None
                )
                if anchor_ms is not None and stream_gaps:
                    gap_index, shift_ms, last_folded = cursor
                    while (
                        gap_index < len(stream_gaps)
                        and anchor_ms >= stream_gaps[gap_index][1]
                    ):
                        shift_ms += (
                            stream_gaps[gap_index][1] - stream_gaps[gap_index][0]
                        )
                        gap_index += 1
                    folded_dts = anchor_ms - shift_ms
                    if (
                        gap_index < len(stream_gaps)
                        and anchor_ms > stream_gaps[gap_index][0]
                    ):
                        folded_dts = stream_gaps[gap_index][0] - (
                            shift_ms
                            - (stream_gaps[gap_index][1] - stream_gaps[gap_index][0])
                        )
                    if last_folded is not None and folded_dts < last_folded:
                        folded_dts = last_folded
                    cursor[:] = [gap_index, shift_ms, folded_dts]
                    if packet.dts is not None:
                        packet.dts = from_ms(folded_dts)
                    if packet.pts is not None:
                        folded_pts = to_ms(packet.pts) - shift_ms
                        if folded_pts < folded_dts:
                            folded_pts = folded_dts
                        packet.pts = from_ms(folded_pts)
                # Do NOT set packet.time_base: values are already in the
                # output stream's units and av 17 rejects muxing after a
                # time_base reassignment on an incoming packet.
                packet.stream = out_stream
                output_container.mux(packet)
        finally:
            output_container.close()
        os.replace(temporary, target)
        return target
    finally:
        input_container.close()
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if source != Path(source_path):
            try:
                source.unlink(missing_ok=True)
            except OSError:
                pass


PROXY_GENERATOR_VERSION = 2
PROXY_DURATION_TOLERANCE_MS = 2_000


def continuous_proxy_marker(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / "continuous.json"


def write_continuous_proxy_marker(
    cache_dir: str | Path, *, expected_duration_ms: int, folded_gaps: int, folded_ms: int
) -> Path:
    marker = continuous_proxy_marker(cache_dir)
    marker.write_text(
        json.dumps(
            {
                "generator_version": PROXY_GENERATOR_VERSION,
                "expected_duration_ms": int(expected_duration_ms),
                "folded_gaps": int(folded_gaps),
                "folded_ms": int(folded_ms),
                "file": "continuous.mkv",
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return marker


def validate_continuous_proxy(
    cache_dir: str | Path,
    ffprobe_path: str | Path,
    *,
    expected_duration_ms: int,
) -> tuple[bool, str]:
    """§18/§19 采用门：时长比例失衡（如 8x 折叠=0.125 比例）直接拒用。

    Returns (ok, reason). ok=False 时调用方必须 fallback 到 optimized+AVSyncMap。
    """
    proxy = Path(cache_dir) / "continuous.mkv"
    if not proxy.is_file():
        return False, "missing"
    try:
        result = run_hidden_subprocess(
            [
                str(ffprobe_path), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", str(proxy),
            ],
            purpose="validate continuous proxy",
            capture_output=True,
            timeout=60,
            check=False,
        )
        payload = json.loads(result.stdout or "{}")
        duration_ms = int(float(payload["format"]["duration"]) * 1000)
    except (OSError, ValueError, KeyError, TypeError):
        return False, "probe_failed"
    if expected_duration_ms <= 0:
        return True, "no_reference"
    delta = abs(duration_ms - expected_duration_ms)
    if delta > PROXY_DURATION_TOLERANCE_MS:
        return False, f"duration_mismatch {duration_ms} vs {expected_duration_ms} (delta {delta}ms)"
    return True, f"ok {duration_ms}ms"


def continuous_proxy_ready(cache_dir: str | Path) -> Path | None:
    path = Path(cache_dir) / "continuous.mkv"
    return path if path.is_file() else None


__all__.extend([
    "build_continuous_proxy", "continuous_proxy_ready",
    "continuous_proxy_marker", "write_continuous_proxy_marker",
    "validate_continuous_proxy", "PROXY_GENERATOR_VERSION",
])
