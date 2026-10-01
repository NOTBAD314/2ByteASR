"""Pure contracts for asynchronous Studio media ingest."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .studio_helpers import probe_media_identity


@dataclass(frozen=True)
class MediaIngestResult:
    generation: int
    project_token: str
    source_path: str
    duration_ms: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    video_timebase: str = ""
    audio_timebase: str = ""
    container_start_ms: float = 0.0
    source_start_ms: float = 0.0
    video_start_ms: float = 0.0
    audio_start_ms: float = 0.0
    video_first_pts_ms: float = 0.0
    audio_first_pts_ms: float = 0.0
    video_best_effort_timestamp_ms: float = 0.0
    audio_best_effort_timestamp_ms: float = 0.0
    sample_timeline_origin_ms: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    rotation: int = 0
    size: int = 0
    mtime_ns: int = 0
    fingerprint: str = ""
    xml_candidates: tuple[str, ...] = ()
    auto_xml_path: str = ""
    error: str = ""
    elapsed_ms: float = 0.0


def _normalized_stem(value: str) -> str:
    stem = value.casefold().strip()
    stem = re.sub(r"[\s_-]+", "", stem)
    return stem


def discover_same_stem_xml(media_path: str | Path) -> tuple[tuple[str, ...], str]:
    """Find bounded same-directory XML matches; ambiguity never auto-binds."""
    media = Path(media_path).resolve()
    if not media.parent.is_dir():
        return (), ""
    wanted = _normalized_stem(media.stem)
    candidates = tuple(
        str(path.resolve())
        for path in sorted(media.parent.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file()
        and path.suffix.casefold() == ".xml"
        and _normalized_stem(path.stem) == wanted
    )
    return candidates, candidates[0] if len(candidates) == 1 else ""


def ingest_media(
    media_path: str | Path,
    *,
    generation: int,
    project_token: str,
    probe: Callable[[str | Path], Mapping[str, object]] = probe_media_identity,
) -> MediaIngestResult:
    """Probe one media source for a background Page worker."""
    started = time.perf_counter()
    source = Path(media_path).resolve()
    try:
        stat = source.stat()
        identity = dict(probe(source))
        candidates, automatic = discover_same_stem_xml(source)
        return MediaIngestResult(
            generation=int(generation),
            project_token=str(project_token),
            source_path=str(source),
            duration_ms=max(0, int(identity.get("duration_ms") or 0)),
            width=max(0, int(identity.get("width") or 0)),
            height=max(0, int(identity.get("height") or 0)),
            fps=max(0.0, float(identity.get("fps") or 0.0)),
            has_video=bool(identity.get("has_video")),
            has_audio=bool(identity.get("has_audio")),
            video_codec=str(identity.get("video_codec") or ""),
            audio_codec=str(identity.get("audio_codec") or ""),
            video_timebase=str(identity.get("video_timebase") or ""),
            audio_timebase=str(identity.get("audio_timebase") or ""),
            container_start_ms=float(identity.get("container_start_ms", identity.get("format_start_ms", 0.0)) or 0.0),
            source_start_ms=float(identity.get("source_start_ms", identity.get("container_start_ms", 0.0)) or 0.0),
            video_start_ms=float(identity.get("video_start_ms", 0.0) or 0.0),
            audio_start_ms=float(identity.get("audio_start_ms", 0.0) or 0.0),
            video_first_pts_ms=float(identity.get("video_first_pts_ms", 0.0) or 0.0),
            audio_first_pts_ms=float(identity.get("audio_first_pts_ms", 0.0) or 0.0),
            video_best_effort_timestamp_ms=float(identity.get("video_best_effort_timestamp_ms", 0.0) or 0.0),
            audio_best_effort_timestamp_ms=float(identity.get("audio_best_effort_timestamp_ms", 0.0) or 0.0),
            sample_timeline_origin_ms=float(identity.get("sample_timeline_origin_ms", identity.get("audio_start_ms", 0.0)) or 0.0),
            sample_rate=max(0, int(identity.get("sample_rate") or 0)),
            channels=max(0, int(identity.get("channels") or 0)),
            rotation=int(identity.get("rotation") or 0),
            size=int(identity.get("size") or stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            fingerprint=str(identity.get("fingerprint") or ""),
            xml_candidates=candidates,
            auto_xml_path=automatic,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    except Exception as exc:
        return MediaIngestResult(
            generation=int(generation),
            project_token=str(project_token),
            source_path=str(source),
            error=str(exc) or type(exc).__name__,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )


def result_matches_request(
    result: MediaIngestResult,
    generation: int,
    project_token: str,
    source_path: str | Path,
) -> bool:
    try:
        source = str(Path(source_path).resolve())
    except (OSError, ValueError):
        return False
    return (
        result.generation == int(generation)
        and result.project_token == str(project_token)
        and result.source_path == source
    )


__all__ = [
    "MediaIngestResult",
    "discover_same_stem_xml",
    "ingest_media",
    "result_matches_request",
]
