"""Canonical project/source/stream timestamp mapping for Studio media.

The editable timeline is a presentation-time domain.  Demuxed packets live in
their stream timestamp domains and may have different origins (a common FLV
case is audio at 21 ms and video at 998 ms).  Keeping the conversion here
prevents playback, waveform extraction and seek code from quietly assuming
that those domains are interchangeable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


def _non_negative(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _timebase(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class MediaTimeMapping:
    """Map project presentation time to normalized source and raw stream PTS.

    ``source_media_ms`` is the demuxer presentation domain used by mpv and
    FFmpeg input-side ``-ss``.  ``stream_pts_ms`` is the raw packet timestamp;
    it is deliberately not treated as project time.
    """

    container_start_ms: float = 0.0
    source_start_ms: float = 0.0
    video_start_ms: float = 0.0
    audio_start_ms: float = 0.0
    duration_ms: float = 0.0
    video_timebase: str = ""
    audio_timebase: str = ""
    sample_rate: int = 0
    sample_timeline_origin_ms: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "container_start_ms", float(self.container_start_ms or 0.0))
        object.__setattr__(self, "video_start_ms", float(self.video_start_ms or 0.0))
        object.__setattr__(self, "audio_start_ms", float(self.audio_start_ms or 0.0))
        object.__setattr__(self, "duration_ms", _non_negative(self.duration_ms))
        object.__setattr__(self, "sample_rate", max(0, int(self.sample_rate or 0)))
        object.__setattr__(self, "sample_timeline_origin_ms", float(self.sample_timeline_origin_ms or 0.0))

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any] | None) -> "MediaTimeMapping":
        value = dict(metadata or {})
        video = value.get("video_metadata") if isinstance(value.get("video_metadata"), Mapping) else value
        audio = value.get("audio_metadata") if isinstance(value.get("audio_metadata"), Mapping) else value
        return cls(
            container_start_ms=float(value.get("container_start_ms", value.get("format_start_ms", 0.0)) or 0.0),
            source_start_ms=float(value.get("source_start_ms", value.get("container_start_ms", value.get("format_start_ms", 0.0))) or 0.0),
            video_start_ms=float(value.get("video_start_ms", video.get("start_time_ms", 0.0)) or 0.0),
            audio_start_ms=float(value.get("audio_start_ms", audio.get("start_time_ms", 0.0)) or 0.0),
            duration_ms=float(value.get("duration_ms", 0.0) or 0.0),
            video_timebase=_timebase(value.get("video_timebase", video.get("time_base", video.get("timebase", "")))),
            audio_timebase=_timebase(value.get("audio_timebase", audio.get("time_base", audio.get("timebase", "")))),
            sample_rate=int(value.get("sample_rate", audio.get("sample_rate", 0)) or 0),
            sample_timeline_origin_ms=float(value.get("sample_timeline_origin_ms", value.get("audio_start_ms", 0.0)) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def project_to_source_ms(
        self,
        project_ms: float,
        *,
        timeline_in_ms: float = 0.0,
        source_in_ms: float = 0.0,
        playback_rate: float = 1.0,
    ) -> float:
        rate = max(0.0001, float(playback_rate or 1.0))
        source = float(source_in_ms) + (float(project_ms) - float(timeline_in_ms)) * rate
        return max(0.0, source)

    def source_to_project_ms(
        self,
        source_ms: float,
        *,
        timeline_in_ms: float = 0.0,
        source_in_ms: float = 0.0,
        playback_rate: float = 1.0,
    ) -> float:
        rate = max(0.0001, float(playback_rate or 1.0))
        return max(0.0, float(timeline_in_ms) + (float(source_ms) - float(source_in_ms)) / rate)

    def source_to_stream_pts_ms(self, source_ms: float, stream: str) -> float:
        origin = self.audio_start_ms if str(stream).casefold() == "audio" else self.video_start_ms
        return float(source_ms) + origin

    def stream_pts_to_source_ms(self, pts_ms: float, stream: str) -> float:
        origin = self.audio_start_ms if str(stream).casefold() == "audio" else self.video_start_ms
        return float(pts_ms) - origin

    def source_to_sample_index(self, source_ms: float) -> int:
        rate = max(1, int(self.sample_rate or 1))
        relative_ms = float(source_ms) - float(self.sample_timeline_origin_ms)
        return max(0, round(relative_ms * rate / 1000.0))

    def describe_seek(self, project_ms: float, *, timeline_in_ms: float = 0.0,
                      source_in_ms: float = 0.0, playback_rate: float = 1.0) -> dict[str, Any]:
        source = self.project_to_source_ms(
            project_ms, timeline_in_ms=timeline_in_ms,
            source_in_ms=source_in_ms, playback_rate=playback_rate,
        )
        return {
            "project_time_ms": round(float(project_ms), 3),
            "source_media_time_ms": round(source, 3),
            "video_stream_pts_ms": round(self.source_to_stream_pts_ms(source, "video"), 3),
            "audio_stream_pts_ms": round(self.source_to_stream_pts_ms(source, "audio"), 3),
            "container_start_ms": round(self.container_start_ms, 3),
            "source_start_ms": round(self.source_start_ms, 3),
            "video_start_ms": round(self.video_start_ms, 3),
            "audio_start_ms": round(self.audio_start_ms, 3),
        }


__all__ = ["MediaTimeMapping"]
