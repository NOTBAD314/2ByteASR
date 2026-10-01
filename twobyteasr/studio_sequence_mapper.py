"""Map edited timeline time <-> source media time, and build mpv EDL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .studio_edit_sequence import EditSequence, VideoSegment, segment_at


@dataclass(frozen=True)
class MappedTime:
    timeline_ms: int
    source_ms: int
    segment_id: str
    source_path: str


def timeline_to_source(sequence: EditSequence, timeline_ms: int) -> MappedTime | None:
    time = max(0, int(timeline_ms))
    segment = segment_at(sequence, time if time < sequence.timeline_duration_ms else max(0, sequence.timeline_duration_ms - 1))
    if segment is None:
        return None
    offset = min(segment.duration_ms, max(0, time - segment.timeline_in_ms))
    return MappedTime(
        timeline_ms=time,
        source_ms=segment.source_in_ms + round(offset * segment.source_duration_ms / max(1, segment.duration_ms)),
        segment_id=segment.id,
        source_path=segment.source_path or sequence.source_path,
    )


def source_to_timeline(sequence: EditSequence, source_ms: int, *, segment: VideoSegment | None = None) -> MappedTime | None:
    time = int(source_ms)
    candidates: Iterable[VideoSegment] = (segment,) if segment is not None else sequence.segments
    for item in candidates:
        if item.source_in_ms <= time < item.source_out_ms or (
            time == item.source_out_ms and item.timeline_out_ms == sequence.timeline_duration_ms
        ):
            offset = min(item.source_duration_ms, max(0, time - item.source_in_ms))
            return MappedTime(
                timeline_ms=item.timeline_in_ms + round(offset * item.duration_ms / max(1, item.source_duration_ms)),
                source_ms=time,
                segment_id=item.id,
                source_path=item.source_path or sequence.source_path,
            )
    return None


def next_segment_after_source(sequence: EditSequence, source_ms: int) -> VideoSegment | None:
    time = int(source_ms)
    later = [item for item in sequence.segments if item.source_in_ms >= time]
    if later:
        return min(later, key=lambda item: (item.timeline_in_ms, item.source_in_ms))
    return None


def map_playhead_between_sequences(
    before: EditSequence,
    after: EditSequence,
    timeline_ms: int,
) -> MappedTime | None:
    """Keep the same source frame across a non-destructive sequence edit.

    A split maps exactly.  When the source frame was removed by a ripple edit,
    the playhead lands on the first surviving frame to its right; if there is
    no such frame it lands at the edited sequence end.  This is also symmetric
    enough for Undo/Redo because the command supplies the actual before/after
    sequence for each direction.
    """
    source = timeline_to_source(before, timeline_ms)
    if source is None:
        return None
    candidates = [s for s in after.segments
                  if (s.source_path or after.source_path) == source.source_path
                  and (s.id == source.segment_id
                       or source.segment_id in after.segment_lineage.get(s.id, [])
                       or s.id in before.segment_lineage.get(source.segment_id, []))]
    for segment in candidates:
        mapped = source_to_timeline(after, source.source_ms, segment=segment)
        if mapped is not None:
            return mapped
    following = next((s for s in candidates if s.source_in_ms >= source.source_ms), None)
    if following is not None:
        return MappedTime(
            timeline_ms=following.timeline_in_ms,
            source_ms=following.source_in_ms,
            segment_id=following.id,
            source_path=following.source_path or after.source_path,
        )
    if not after.segments:
        return None
    tail = after.segments[-1]
    return MappedTime(
        timeline_ms=after.timeline_duration_ms,
        source_ms=tail.source_out_ms,
        segment_id=tail.id,
        source_path=tail.source_path or after.source_path,
    )


def restore_source_seconds(sequence: EditSequence, timeline_ms: int) -> float | None:
    """Source seconds for loading mpv at a saved timeline playhead.

    Identity (linear) sequences fall back to the raw playhead so probe-less
    projects keep their legacy restore behaviour.
    """

    time = max(0, int(timeline_ms))
    if not time and sequence.is_linear_source():
        return None
    if sequence.is_linear_source():
        return time / 1000.0
    mapped = timeline_to_source(sequence, time)
    if mapped is not None:
        return mapped.source_ms / 1000.0
    nxt = next_segment_after_source(sequence, time)
    if nxt is not None:
        return nxt.source_in_ms / 1000.0
    if sequence.segments:
        return sequence.segments[-1].source_in_ms / 1000.0
    return time / 1000.0


def export_source_slices(
    sequence: EditSequence,
    start_ms: int | None = None,
    duration_ms: int | None = None,
) -> list[tuple[float, float]]:
    """Source (in, out) seconds for the export window, in timeline order."""
    start = 0 if start_ms is None else max(0, int(start_ms))
    end = sequence.timeline_duration_ms if duration_ms is None else start + max(0, int(duration_ms))
    slices: list[tuple[float, float]] = []
    for segment in sequence.segments:
        overlap_in = max(start, segment.timeline_in_ms)
        overlap_out = min(end, segment.timeline_out_ms)
        if overlap_out <= overlap_in:
            continue
        rate = segment.source_duration_ms / max(1, segment.duration_ms)
        source_in = segment.source_in_ms + (overlap_in - segment.timeline_in_ms) * rate
        source_out = segment.source_in_ms + (overlap_out - segment.timeline_in_ms) * rate
        slices.append((source_in / 1000.0, source_out / 1000.0))
    return slices


def _edl_path(path: str) -> str:
    # mpv 0.41 on Windows accepts POSIX drive paths in edl:// without percent-encoding.
    return Path(path).resolve().as_posix()


def write_mpv_edl(sequence: EditSequence, dest: str | Path) -> Path:
    """Write an mpv EDL v0 file. Timeline time == EDL playback time."""
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# mpv EDL v0"]
    for segment in sequence.segments:
        length = max(0.001, segment.duration_ms / 1000.0)
        start = segment.source_in_ms / 1000.0
        path = _edl_path(segment.source_path or sequence.source_path)
        lines.append(f"{path},{start:.6f},{length:.6f}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def edl_protocol_url(sequence: EditSequence) -> str:
    parts: list[str] = []
    for segment in sequence.segments:
        length = max(0.001, segment.duration_ms / 1000.0)
        start = segment.source_in_ms / 1000.0
        path = _edl_path(segment.source_path or sequence.source_path)
        parts.append(f"{path},{start:.6f},{length:.6f}")
    return "edl://" + ";".join(parts)
