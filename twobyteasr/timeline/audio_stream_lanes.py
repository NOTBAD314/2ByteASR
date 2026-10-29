"""Which source audio stream each audio lane plays, and how to show it.

2026-10-24 (multi-track import): a lane's identity is (source asset, relative
audio ordinal ``0:a:N``); the absolute stream index and the user-facing name
come from the asset's probed stream records (``media.audio_streams``). The
timeline, the recognition track picker and the recognition queue all read
lanes through here, so a row number on screen is never mistaken for a
stream index.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..media.audio_streams import asset_streams, stream_by_ordinal

_JOB_SEPARATOR = "|a"  # '|' cannot occur in a Windows path


def waveform_job(path: str, audio_stream: int = 0) -> str:
    """Waveform work item: the path itself for the first stream (as before)."""
    return str(path) if int(audio_stream or 0) <= 0 else f"{path}{_JOB_SEPARATOR}{int(audio_stream)}"


def split_waveform_job(job: str) -> tuple[str, int]:
    text = str(job or "")
    head, sep, tail = text.rpartition(_JOB_SEPARATOR)
    if sep and tail.isdigit():
        return head, int(tail)
    return text, 0


def waveform_streams_for(project, asset_id: str) -> tuple[list[int], list[int]]:
    """(streams the A lanes play, further streams) of one source on the timeline."""
    lead: list[int] = []
    rest: list[int] = []
    for track in project.audio_tracks:
        for clip in track.clips:
            if clip.asset_id != asset_id:
                continue
            target = rest if getattr(track, "stream_ordinal", -1) >= 0 else lead
            if clip.stream_index not in target:
                target.append(int(clip.stream_index))
    if not lead and not rest:
        lead = [0]
    return lead, [stream for stream in rest if stream not in lead]


def stream_time_mapping(project, source_path: str, audio_stream: int = 0) -> dict | None:
    """The project's media time mapping, moved to one stream's own start.

    Waveform frames start at the stream's first sample; a dub track that
    begins 3 s into the file must be drawn from 3 s.
    """
    if project is None:
        return None
    mapping = dict(getattr(project, "studio_state", {}).get("media_time_mapping", {}) or {})
    if int(audio_stream or 0) <= 0:
        return mapping
    try:
        wanted = str(Path(source_path).resolve())
        asset = next(a for a in project.media_pool if str(Path(a.canonical_source).resolve()) == wanted)
    except (StopIteration, OSError, ValueError):
        return mapping
    first, row = stream_by_ordinal(asset, 0), stream_by_ordinal(asset, audio_stream)
    if not row:
        return mapping
    delta = float(row.get("start_ms") or 0.0) - float((first or {}).get("start_ms") or 0.0)
    # Both from the first stream's values (a dropped file's mapping may lack
    # the origin; it then falls back to the *unshifted* audio start).
    audio_start = float(mapping.get("audio_start_ms", 0.0) or 0.0)
    origin = float(mapping.get("sample_timeline_origin_ms", audio_start) or 0.0)
    mapping["audio_start_ms"] = audio_start + delta
    mapping["sample_timeline_origin_ms"] = origin + delta
    return mapping


def lane_route_id(project, lane_id: str) -> str:
    """The id mute/solo/mix use for a lane: its video track for a linked A lane."""
    group = next((g for g in project.av_track_groups if g.linked and g.audio_track_id == lane_id
                  and g.video_track_id), None)
    return group.video_track_id if group is not None else str(lane_id)


def lane_sources(project, track) -> list[tuple[Any, int]]:
    """(asset, ordinal) pairs a lane plays, in timeline order, without repeats."""
    assets = {asset.asset_id: asset for asset in project.media_pool}
    seen: list[tuple[Any, int]] = []
    for clip in sorted(track.clips, key=lambda c: (c.timeline_in_ms, c.id)):
        asset = assets.get(clip.asset_id)
        if asset is None:
            continue
        key = (asset, int(clip.stream_index))
        if all(item[0].asset_id != asset.asset_id or item[1] != key[1] for item in seen):
            seen.append(key)
    return seen


def lane_stream_record(project, track) -> tuple[Any, dict | None]:
    """The main (asset, stream record) of a lane: its first source in time."""
    sources = lane_sources(project, track)
    if not sources:
        return None, None
    asset, ordinal = sources[0]
    return asset, stream_by_ordinal(asset, ordinal)


def lane_label(project, track, *, with_channels: bool = True):
    """'音轨 2｜中文配音｜中文｜立体声' for a lane, or None without stream data."""
    from ..media.audio_streams import stream_label
    _asset, record = lane_stream_record(project, track)
    return stream_label(record, with_channels=with_channels) if record else None


def has_multitrack_source(project) -> bool:
    """True when some source on the timeline carries more than one audio stream."""
    used = {clip.asset_id for track in (*project.video_tracks, *project.audio_tracks) for clip in track.clips}
    return any(len(asset_streams(asset)) > 1 for asset in project.media_pool if asset.asset_id in used)


def recognizable_lanes(project) -> list[dict]:
    """Audio lanes the recognition picker can offer, in timeline order.

    Each row keeps the identity the queue needs (lane id, source asset,
    relative ordinal and absolute stream index), what the user reads, and
    why a lane cannot be used (an undecodable stream, an offline file). A
    lane without clips has nothing to recognize and is left out.
    """
    from ..projects.studio_project import _asset_has_audio
    rows = []
    for track in project.audio_tracks:
        sources = lane_sources(project, track)
        if not sources:
            continue
        asset, ordinal = sources[0]
        if not _asset_has_audio(asset):
            continue
        record = stream_by_ordinal(asset, ordinal)
        problem = ""
        if record is not None and not record.get("decodable", True):
            problem = str(record.get("problem") or "无法解码")
        elif getattr(asset, "offline", False) or not Path(str(asset.canonical_source or "")).is_file():
            problem = "素材文件找不到（离线）"
        source_names = list(dict.fromkeys(Path(a.canonical_source).name for a, _ in sources))
        rows.append({
            "lane_id": track.id,
            "route_id": lane_route_id(project, track.id),
            "asset_id": asset.asset_id,
            "source_path": str(asset.canonical_source),
            "source_name": source_names[0] if source_names else "",
            "source_names": source_names,
            "fingerprint": str(asset.fingerprint or ""),
            "ordinal": int(ordinal),
            "stream_index": int(record["index"]) if record else -1,
            "record": dict(record) if record else None,
            "follower": getattr(track, "stream_ordinal", -1) >= 0,
            "muted": bool(track.muted),
            "problem": problem,
        })
    return rows


def source_key(row: dict) -> str:
    """Remembered-choice key of one lane: bound to its source, not a row number."""
    fingerprint = str(row.get("fingerprint") or row.get("asset_id") or "")
    return f"{fingerprint}:a{int(row.get('ordinal', 0))}:s{int(row.get('stream_index', -1))}"


__all__ = [
    "has_multitrack_source", "lane_label", "lane_route_id", "lane_sources", "lane_stream_record",
    "recognizable_lanes", "source_key", "split_waveform_job", "stream_time_mapping", "waveform_job",
    "waveform_streams_for",
]
