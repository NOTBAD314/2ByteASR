"""Single project-timeline ↔ source-media mapping for every clip.

One Project PlaybackClock owns time. Decoders, waveform, thumbnails, export
and timeline edits all call these functions instead of inventing a second
offset. Secondary players must never write the project clock.

    source_time = source_in + (project_time - timeline_in) * playback_rate
    project_time = timeline_in + (source_time - source_in) / playback_rate
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class ClipTiming:
    timeline_in_ms: int
    timeline_out_ms: int
    source_in_ms: int
    source_out_ms: int
    playback_rate: float = 1.0
    clip_id: str = ""
    track_id: str = ""
    source_path: str = ""

    @property
    def rate(self) -> float:
        value = float(self.playback_rate or 1.0)
        return value if value > 0 else 1.0

    def active_at(self, project_ms: int) -> bool:
        time_ms = int(project_ms)
        return int(self.timeline_in_ms) <= time_ms < int(self.timeline_out_ms)


@dataclass(frozen=True, slots=True)
class MappedClipTime:
    project_ms: int
    source_ms: int
    clip_id: str
    track_id: str
    source_path: str
    playback_rate: float
    active: bool


@dataclass(frozen=True, slots=True)
class ClipTimeTrace:
    project_target_ms: int
    clip_id: str
    track_id: str
    timeline_in_ms: int
    source_in_ms: int
    playback_rate: float
    computed_source_ms: int | None
    decoder_requested_ms: int | None
    decoder_reported_ms: int | None
    frame_pts_ms: int | None
    presentation_ms: int | None
    generation: int = 0
    reason: str = ""


_TRACE: deque[ClipTimeTrace] = deque(maxlen=4096)


def clip_timing_from(value: Any, **overrides: Any) -> ClipTiming:
    if isinstance(value, ClipTiming):
        if not overrides:
            return value
        payload = asdict(value)
        payload.update(overrides)
        return ClipTiming(**payload)
    if isinstance(value, Mapping):
        payload = {
            "timeline_in_ms": int(value.get("timeline_in_ms") or 0),
            "timeline_out_ms": int(value.get("timeline_out_ms") or 0),
            "source_in_ms": int(value.get("source_in_ms") or 0),
            "source_out_ms": int(value.get("source_out_ms") or 0),
            "playback_rate": float(value.get("playback_rate") or 1.0),
            "clip_id": str(value.get("clip_id") or value.get("id") or ""),
            "track_id": str(value.get("track_id") or ""),
            "source_path": str(value.get("source_path") or ""),
        }
        payload.update(overrides)
        return ClipTiming(**payload)
    payload = {
        "timeline_in_ms": int(getattr(value, "timeline_in_ms", 0) or 0),
        "timeline_out_ms": int(getattr(value, "timeline_out_ms", 0) or 0),
        "source_in_ms": int(getattr(value, "source_in_ms", 0) or 0),
        "source_out_ms": int(getattr(value, "source_out_ms", 0) or 0),
        "playback_rate": float(getattr(value, "playback_rate", 1.0) or 1.0),
        "clip_id": str(getattr(value, "id", getattr(value, "clip_id", "")) or ""),
        "track_id": str(getattr(value, "track_id", "") or ""),
        "source_path": str(getattr(value, "source_path", "") or ""),
    }
    payload.update(overrides)
    return ClipTiming(**payload)


def project_to_source(timing: Any, project_ms: int) -> int | None:
    clip = clip_timing_from(timing)
    time_ms = int(project_ms)
    if not clip.active_at(time_ms):
        return None
    source = clip.source_in_ms + (time_ms - clip.timeline_in_ms) * clip.rate
    last = max(clip.source_in_ms, clip.source_out_ms - 1)
    return int(min(max(clip.source_in_ms, round(source)), last))


def project_to_source_exact(timing: Any, project_seconds: Fraction) -> Fraction | None:
    """Production frame mapping before any millisecond quantization/clamping."""
    clip = clip_timing_from(timing)
    milliseconds = project_seconds * 1000
    if not clip.timeline_in_ms <= milliseconds < clip.timeline_out_ms:
        return None
    return (Fraction(clip.source_in_ms) + (milliseconds-clip.timeline_in_ms)*Fraction(str(clip.rate)))/1000


def source_to_project(timing: Any, source_ms: int) -> int | None:
    clip = clip_timing_from(timing)
    time_ms = int(source_ms)
    if time_ms < clip.source_in_ms or time_ms > clip.source_out_ms:
        if time_ms != clip.source_out_ms:
            return None
    project = clip.timeline_in_ms + (time_ms - clip.source_in_ms) / clip.rate
    last = max(clip.timeline_in_ms, clip.timeline_out_ms - 1)
    mapped = int(round(project))
    if mapped < clip.timeline_in_ms or mapped >= clip.timeline_out_ms:
        if mapped == clip.timeline_out_ms:
            return clip.timeline_out_ms
        return None
    return min(max(clip.timeline_in_ms, mapped), last)


def map_project_time(timing: Any, project_ms: int) -> MappedClipTime:
    clip = clip_timing_from(timing)
    source = project_to_source(clip, project_ms)
    return MappedClipTime(
        project_ms=int(project_ms),
        source_ms=int(source if source is not None else clip.source_in_ms),
        clip_id=clip.clip_id,
        track_id=clip.track_id,
        source_path=clip.source_path,
        playback_rate=clip.rate,
        active=source is not None,
    )


def moved_timing(timing: Any, timeline_in_ms: int) -> ClipTiming:
    clip = clip_timing_from(timing)
    duration = max(0, clip.timeline_out_ms - clip.timeline_in_ms)
    start = max(0, int(timeline_in_ms))
    return clip_timing_from(
        clip,
        timeline_in_ms=start,
        timeline_out_ms=start + duration,
    )


def trimmed_left(timing: Any, timeline_in_ms: int) -> ClipTiming:
    clip = clip_timing_from(timing)
    new_in = min(max(0, int(timeline_in_ms)), clip.timeline_out_ms - 1)
    delta = new_in - clip.timeline_in_ms
    source_in = clip.source_in_ms + int(round(delta * clip.rate))
    source_in = min(max(0, source_in), clip.source_out_ms - 1)
    return clip_timing_from(
        clip,
        timeline_in_ms=new_in,
        source_in_ms=source_in,
    )


def trimmed_right(timing: Any, timeline_out_ms: int) -> ClipTiming:
    clip = clip_timing_from(timing)
    new_out = max(clip.timeline_in_ms + 1, int(timeline_out_ms))
    source_out = clip.source_in_ms + int(round((new_out - clip.timeline_in_ms) * clip.rate))
    source_out = max(clip.source_in_ms + 1, source_out)
    return clip_timing_from(
        clip,
        timeline_out_ms=new_out,
        source_out_ms=source_out,
    )


def frame_tolerance_ms(fps: float) -> int:
    rate = float(fps or 0.0)
    if rate <= 0:
        return 42
    return max(16, int(round(1000.0 / rate)))


def record_clip_time_trace(trace: ClipTimeTrace) -> ClipTimeTrace:
    _TRACE.append(trace)
    return trace


def clip_time_traces() -> list[ClipTimeTrace]:
    return list(_TRACE)


def clear_clip_time_traces() -> None:
    _TRACE.clear()


__all__ = [
    "ClipTimeTrace",
    "ClipTiming",
    "MappedClipTime",
    "clear_clip_time_traces",
    "clip_time_traces",
    "clip_timing_from",
    "frame_tolerance_ms",
    "map_project_time",
    "moved_timing",
    "project_to_source",
    "record_clip_time_trace",
    "source_to_project",
    "trimmed_left",
    "trimmed_right",
]
