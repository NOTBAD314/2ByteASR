"""Single-source non-destructive edit sequence — source of truth for P6.

EditSequence is the only place video cuts live. Timeline paint, playback,
export, and project save all read this object. The source media file is
never rewritten.
"""

from __future__ import annotations

import bisect
import copy
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Generic, Iterable, Mapping, Sequence, TypeVar

from .studio_project import StudioCue, StudioMedia, SubtitleProject


EDIT_SEQUENCE_VERSION = 1
MIN_SEGMENT_MS = 40
MIN_CUE_MS = 40


_T = TypeVar("_T")


class TemporalIntervalIndex(Generic[_T]):
    """Start-sorted interval index with prefix-max ends for viewport queries."""

    def __init__(self, entries: Iterable[tuple[int, int, _T]] = ()) -> None:
        ordered = sorted(
            ((int(start), max(int(start) + 1, int(end)), item) for start, end, item in entries),
            key=lambda value: (value[0], value[1]),
        )
        self._entries = tuple(ordered)
        self._starts = tuple(item[0] for item in ordered)
        prefix: list[int] = []
        maximum = -1
        for _start, end, _item in ordered:
            maximum = max(maximum, end)
            prefix.append(maximum)
        self._prefix_max_ends = tuple(prefix)

    def query(self, start_ms: int, end_ms: int) -> tuple[_T, ...]:
        start, end = int(start_ms), max(int(start_ms) + 1, int(end_ms))
        cursor = bisect.bisect_left(self._starts, end) - 1
        matches: list[_T] = []
        while cursor >= 0 and self._prefix_max_ends[cursor] > start:
            item_start, item_end, item = self._entries[cursor]
            if item_start < end and item_end > start:
                matches.append(item)
            cursor -= 1
        matches.reverse()
        return tuple(matches)

    def __len__(self) -> int:
        return len(self._entries)


def _clean_id(value: Any) -> str:
    text = str(value or "").strip()
    return text or uuid.uuid4().hex[:12]


def _int_ms(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return int(default)


def _string_list(value: Any) -> list[str]:
    """Coerce LLM/persisted payloads into a clean string list.

    Models regularly return a plain string where the schema asks for an
    array; iterating such a string silently splits it into per-character
    rows (user-visible as one-character-per-line evidence). A bare string
    is kept as a single row instead.
    """

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass
class VideoSegment:
    id: str
    source_path: str
    source_in_ms: int
    source_out_ms: int
    timeline_in_ms: int
    timeline_out_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, int(self.timeline_out_ms) - int(self.timeline_in_ms))

    @property
    def source_duration_ms(self) -> int:
        return max(0, int(self.source_out_ms) - int(self.source_in_ms))

    def validate(self) -> None:
        self.id = _clean_id(self.id)
        self.source_path = str(self.source_path or "")
        self.source_in_ms = _int_ms(self.source_in_ms)
        self.source_out_ms = _int_ms(self.source_out_ms)
        self.timeline_in_ms = _int_ms(self.timeline_in_ms)
        self.timeline_out_ms = _int_ms(self.timeline_out_ms)
        if self.source_out_ms < self.source_in_ms:
            raise ValueError(f"segment {self.id} has empty source range")
        if self.timeline_out_ms < self.timeline_in_ms:
            raise ValueError(f"segment {self.id} has empty timeline range")
        source_dur = self.source_out_ms - self.source_in_ms
        timeline_dur = self.timeline_out_ms - self.timeline_in_ms
        # A projected variable-rate clip already has an authored timeline
        # duration. Only fill missing legacy timing, never force it to 1x.
        if timeline_dur == 0 and source_dur > 0:
            self.timeline_out_ms = self.timeline_in_ms + source_dur

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VideoSegment":
        data = dict(payload)
        segment = cls(
            id=str(data.get("id") or ""),
            source_path=str(data.get("source_path") or ""),
            source_in_ms=_int_ms(data.get("source_in_ms", data.get("source_in"))),
            source_out_ms=_int_ms(data.get("source_out_ms", data.get("source_out"))),
            timeline_in_ms=_int_ms(data.get("timeline_in_ms", data.get("timeline_in"))),
            timeline_out_ms=_int_ms(data.get("timeline_out_ms", data.get("timeline_out"))),
        )
        segment.validate()
        return segment


@dataclass
class HighlightCandidate:
    id: str
    title: str
    source_in_ms: int
    source_out_ms: int
    score: float = 0.0
    reason: str = ""
    danmaku_signal: dict[str, Any] = field(default_factory=dict)
    quotes: list[str] = field(default_factory=list)
    status: str = "suggested"  # suggested | accepted | ignored
    origin: str = "ai"  # ai | manual | local(2026-09-19:本地热度回退,未做事件理解)
    grade: str = ""
    hook: str = ""
    # 2026-09-18：剪辑分析五字段（用户规约）——事件概括与编辑判断分离，
    # 弹幕/字幕只作 evidence。旧工程缺省为空，UI 自动回退旧字段。
    event_summary: str = ""
    clip_reason: str = ""
    context_required: str = ""
    danmaku_evidence: list[str] = field(default_factory=list)
    subtitle_evidence: list[str] = field(default_factory=list)
    # 2026-09-19 P1：信号范围内的完整字幕上下文（"发生了什么"的可追溯
    # 证据；重生成解释/人工核对共享这一份，additive 字段）。
    subtitle_context: list[str] = field(default_factory=list)
    edit_direction: str = ""
    subtitle_emphasis: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    category: str = "other"
    signal_in_ms: int | None = None
    signal_out_ms: int | None = None
    context_in_ms: int | None = None
    context_out_ms: int | None = None

    def validate(self) -> None:
        self.id = _clean_id(self.id)
        self.title = str(self.title or "候选片段")
        self.source_in_ms = _int_ms(self.source_in_ms)
        self.source_out_ms = max(self.source_in_ms + MIN_SEGMENT_MS, _int_ms(self.source_out_ms))
        self.signal_in_ms = self.source_in_ms if self.signal_in_ms is None else _int_ms(self.signal_in_ms)
        self.signal_out_ms = self.source_out_ms if self.signal_out_ms is None else _int_ms(self.signal_out_ms)
        self.signal_in_ms = max(self.source_in_ms, min(self.source_out_ms - 1, self.signal_in_ms))
        self.signal_out_ms = max(self.signal_in_ms + 1, min(self.source_out_ms, self.signal_out_ms))
        self.context_in_ms = self.source_in_ms if self.context_in_ms is None else _int_ms(self.context_in_ms)
        self.context_out_ms = self.source_out_ms if self.context_out_ms is None else _int_ms(self.context_out_ms)
        self.context_in_ms = max(
            0,
            min(self.context_in_ms, self.source_in_ms, self.signal_in_ms),
        )
        self.context_out_ms = max(
            self.context_in_ms + 1,
            self.context_out_ms,
            self.source_out_ms,
            self.signal_out_ms,
        )
        try:
            score = float(self.score)
            self.score = max(0.0, min(1.0, score / 100.0 if score > 1.0 else score))
        except (TypeError, ValueError):
            self.score = 0.0
        self.reason = str(self.reason or "")
        self.danmaku_signal = dict(self.danmaku_signal or {})
        self.quotes = _string_list(self.quotes)
        if self.status not in {"suggested", "accepted", "ignored"}:
            self.status = "suggested"
        if self.origin not in {"ai", "manual", "local"}:
            self.origin = "ai"
        if self.grade not in {"强烈推荐", "推荐", "可考虑"}:
            self.grade = "强烈推荐" if self.score >= 0.85 else "推荐" if self.score >= 0.68 else "可考虑"
        self.hook = str(self.hook or "")
        self.danmaku_evidence = _string_list(self.danmaku_evidence)
        self.subtitle_evidence = _string_list(self.subtitle_evidence)
        self.edit_direction = str(self.edit_direction or "")
        self.subtitle_emphasis = _string_list(self.subtitle_emphasis)
        self.risk_notes = _string_list(self.risk_notes)
        allowed_categories = {"funny", "chaos", "reaction", "story", "clutch", "emotional", "tutorial", "other"}
        if self.category not in allowed_categories:
            self.category = "other"

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "title": self.title,
            "source_in_ms": self.source_in_ms,
            "source_out_ms": self.source_out_ms,
            "score": self.score,
            "reason": self.reason,
            "danmaku_signal": copy.deepcopy(self.danmaku_signal),
            "quotes": list(self.quotes),
            "status": self.status,
            "origin": self.origin,
            "grade": self.grade,
            "hook": self.hook,
            "danmaku_evidence": list(self.danmaku_evidence),
            "subtitle_evidence": list(self.subtitle_evidence),
            "subtitle_context": list(self.subtitle_context),
            "edit_direction": self.edit_direction,
            "subtitle_emphasis": list(self.subtitle_emphasis),
            "risk_notes": list(self.risk_notes),
            "category": self.category,
            "signal_in_ms": self.signal_in_ms,
            "signal_out_ms": self.signal_out_ms,
            "context_in_ms": self.context_in_ms,
            "context_out_ms": self.context_out_ms,
            "signal_range": {
                "start_ms": self.signal_in_ms,
                "end_ms": self.signal_out_ms,
            },
            "context_range": {
                "start_ms": self.context_in_ms,
                "end_ms": self.context_out_ms,
            },
            "recommended_range": {
                "start_ms": self.source_in_ms,
                "end_ms": self.source_out_ms,
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HighlightCandidate":
        data = dict(payload)
        signal_range = data.get("signal_range") if isinstance(data.get("signal_range"), Mapping) else {}
        context_range = data.get("context_range") if isinstance(data.get("context_range"), Mapping) else {}
        recommended_range = data.get("recommended_range") if isinstance(data.get("recommended_range"), Mapping) else {}
        item = cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            source_in_ms=_int_ms(data.get("source_in_ms", data.get("source_in", recommended_range.get("start_ms")))),
            source_out_ms=_int_ms(data.get("source_out_ms", data.get("source_out", recommended_range.get("end_ms")))),
            score=float(data.get("score") or 0.0),
            reason=str(data.get("reason") or ""),
            danmaku_signal=dict(data.get("danmaku_signal") or {}),
            quotes=_string_list(data.get("quotes")),
            status=str(data.get("status") or "suggested"),
            origin=str(data.get("origin") or "ai"),
            grade=str(data.get("grade") or ""),
            hook=str(data.get("hook") or ""),
            danmaku_evidence=_string_list(data.get("danmaku_evidence")),
            subtitle_evidence=_string_list(data.get("subtitle_evidence")),
            subtitle_context=_string_list(data.get("subtitle_context")),
            edit_direction=str(data.get("edit_direction") or ""),
            subtitle_emphasis=_string_list(data.get("subtitle_emphasis")),
            risk_notes=_string_list(data.get("risk_notes")),
            category=str(data.get("category") or "other"),
            signal_in_ms=None if data.get("signal_in_ms", signal_range.get("start_ms")) is None else _int_ms(data.get("signal_in_ms", signal_range.get("start_ms"))),
            signal_out_ms=None if data.get("signal_out_ms", signal_range.get("end_ms")) is None else _int_ms(data.get("signal_out_ms", signal_range.get("end_ms"))),
            context_in_ms=None if data.get("context_in_ms", context_range.get("start_ms")) is None else _int_ms(data.get("context_in_ms", context_range.get("start_ms"))),
            context_out_ms=None if data.get("context_out_ms", context_range.get("end_ms")) is None else _int_ms(data.get("context_out_ms", context_range.get("end_ms"))),
        )
        item.validate()
        return item


@dataclass
class TimelineMarker:
    id: str
    time_ms: int
    label: str = ""
    kind: str = "note"

    def validate(self) -> None:
        self.id = _clean_id(self.id)
        self.time_ms = _int_ms(self.time_ms)
        self.label = str(self.label or "")
        self.kind = str(self.kind or "note") or "note"

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TimelineMarker":
        data = dict(payload)
        marker = cls(
            id=str(data.get("id") or ""),
            time_ms=_int_ms(data.get("time_ms", data.get("time"))),
            label=str(data.get("label") or ""),
            kind=str(data.get("kind") or "note"),
        )
        marker.validate()
        return marker


@dataclass
class EditSequence:
    version: int = EDIT_SEQUENCE_VERSION
    video_track_locked: bool = True
    source_path: str = ""
    source_duration_ms: int = 0
    segments: list[VideoSegment] = field(default_factory=list)
    clip_candidates: list[HighlightCandidate] = field(default_factory=list)
    markers: list[TimelineMarker] = field(default_factory=list)
    in_point_ms: int | None = None
    out_point_ms: int | None = None
    selected_segment_id: str = ""
    danmaku_path: str = ""
    empty_timeline: bool = False
    # Explicit split ancestry; repeated uses of the same file are distinct.
    segment_lineage: dict[str, list[str]] = field(default_factory=dict)

    def validate(self) -> None:
        self.version = int(self.version or EDIT_SEQUENCE_VERSION)
        self.video_track_locked = bool(self.video_track_locked)
        self.source_path = str(self.source_path or "")
        self.source_duration_ms = _int_ms(self.source_duration_ms)
        self.danmaku_path = str(self.danmaku_path or "")
        self.empty_timeline = bool(self.empty_timeline)
        self.selected_segment_id = str(self.selected_segment_id or "")
        for segment in self.segments:
            segment.validate()
            if not segment.source_path:
                segment.source_path = self.source_path
        # Validation preserves authored positions. Closing gaps is an explicit
        # ripple operation, never a side effect of delete/undo/save/reopen.
        self.segments.sort(key=lambda segment: (segment.timeline_in_ms, segment.id))
        for candidate in self.clip_candidates:
            candidate.validate()
        for marker in self.markers:
            marker.validate()
        if self.in_point_ms is not None:
            self.in_point_ms = int(self.in_point_ms)
        if self.out_point_ms is not None:
            self.out_point_ms = int(self.out_point_ms)

    def normalize_timeline(self) -> None:
        cursor = 0
        kept: list[VideoSegment] = []
        for segment in self.segments:
            # Ripple closes gaps; it must not turn an authored 2x clip into 1x.
            duration = segment.duration_ms
            if duration < MIN_SEGMENT_MS and not (duration == 0 and not kept):
                continue
            segment.timeline_in_ms = cursor
            segment.timeline_out_ms = cursor + duration
            cursor = segment.timeline_out_ms
            kept.append(segment)
        self.segments = kept

    @property
    def timeline_duration_ms(self) -> int:
        if not self.segments:
            return 0 if self.empty_timeline else int(self.source_duration_ms)
        return int(self.segments[-1].timeline_out_ms)

    def is_identity(self) -> bool:
        if len(self.segments) != 1:
            return False
        segment = self.segments[0]
        return (
            segment.source_in_ms == 0
            and segment.timeline_in_ms == 0
            and segment.source_out_ms == self.source_duration_ms
            and segment.timeline_out_ms == self.source_duration_ms
        )

    def is_linear_source(self) -> bool:
        """True when playback of the original file matches the timeline."""
        if not self.segments:
            return not self.empty_timeline
        expected_source = 0
        expected_timeline = 0
        for segment in self.segments:
            if segment.source_in_ms != expected_source:
                return False
            if segment.timeline_in_ms != expected_timeline:
                return False
            expected_source = segment.source_out_ms
            expected_timeline = segment.timeline_out_ms
        return expected_source == self.source_duration_ms

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "version": self.version,
            "video_track_locked": self.video_track_locked,
            "source_path": self.source_path,
            "source_duration_ms": self.source_duration_ms,
            "segments": [item.to_dict() for item in self.segments],
            "clip_candidates": [item.to_dict() for item in self.clip_candidates],
            "markers": [item.to_dict() for item in self.markers],
            "in_point_ms": self.in_point_ms,
            "out_point_ms": self.out_point_ms,
            "selected_segment_id": self.selected_segment_id,
            "danmaku_path": self.danmaku_path,
            "empty_timeline": self.empty_timeline,
            "segment_lineage": copy.deepcopy(self.segment_lineage),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        media: StudioMedia | None = None,
    ) -> "EditSequence":
        data = dict(payload) if isinstance(payload, Mapping) else {}
        source_path = str(data.get("source_path") or (media.path if media else ""))
        source_duration = _int_ms(
            data.get("source_duration_ms"),
            int(media.duration_ms if media else 0),
        )
        sequence = cls(
            version=int(data.get("version") or EDIT_SEQUENCE_VERSION),
            # The lock field was introduced after the first project fixtures.
            # Missing means the legacy/default locked V1 track, not unlocked.
            video_track_locked=bool(data.get("video_track_locked", True)),
            source_path=source_path,
            source_duration_ms=source_duration,
            segments=[
                VideoSegment.from_dict(item)
                for item in data.get("segments", [])
                if isinstance(item, Mapping)
            ],
            clip_candidates=[
                HighlightCandidate.from_dict(item)
                for item in data.get("clip_candidates", [])
                if isinstance(item, Mapping)
            ],
            markers=[
                TimelineMarker.from_dict(item)
                for item in data.get("markers", [])
                if isinstance(item, Mapping)
            ],
            in_point_ms=None if data.get("in_point_ms") is None else int(data["in_point_ms"]),
            out_point_ms=None if data.get("out_point_ms") is None else int(data["out_point_ms"]),
            selected_segment_id=str(data.get("selected_segment_id") or ""),
            danmaku_path=str(data.get("danmaku_path") or ""),
            empty_timeline=bool(data.get("empty_timeline", False)),
            segment_lineage=copy.deepcopy(data.get("segment_lineage") or {}),
        )
        if not sequence.segments and not sequence.empty_timeline:
            sequence.segments = [identity_segment(source_path, source_duration)]
        sequence.validate()
        return sequence


def identity_segment(source_path: str, duration_ms: int) -> VideoSegment:
    duration = max(0, int(duration_ms))
    return VideoSegment(
        id=f"seg-{uuid.uuid4().hex[:10]}",
        source_path=str(source_path or ""),
        source_in_ms=0,
        source_out_ms=duration,
        timeline_in_ms=0,
        timeline_out_ms=duration,
    )


def identity_sequence(media: StudioMedia) -> EditSequence:
    duration = max(0, int(media.duration_ms or 0))
    sequence = EditSequence(
        source_path=str(media.path or ""),
        source_duration_ms=duration,
        video_track_locked=False,
        empty_timeline=False,
        segments=[identity_segment(str(media.path or ""), duration)],
    )
    sequence.validate()
    return sequence


class EditSequenceRuntime:
    """Project-lifetime canonical sequence plus indexes for frequent reads."""

    def __init__(self, sequence: EditSequence) -> None:
        self.sequence = sequence
        self.revision = 0
        self.segment_by_id: dict[str, VideoSegment] = {}
        self.candidate_by_id: dict[str, HighlightCandidate] = {}
        self.marker_by_id: dict[str, TimelineMarker] = {}
        self._segment_starts: tuple[int, ...] = ()
        self._segment_index: TemporalIntervalIndex[VideoSegment] = TemporalIntervalIndex()
        self._source_segment_index: TemporalIntervalIndex[VideoSegment] = TemporalIntervalIndex()
        self._segment_order_by_id: dict[str, int] = {}
        self._candidate_index: TemporalIntervalIndex[HighlightCandidate] = TemporalIntervalIndex()
        self._marker_index: TemporalIntervalIndex[TimelineMarker] = TemporalIntervalIndex()
        self.reindex(validate=False)

    def __deepcopy__(self, memo):
        clone = type(self)(copy.deepcopy(self.sequence, memo))
        memo[id(self)] = clone
        clone.revision = self.revision
        return clone

    def replace(self, sequence: EditSequence, *, validate: bool = True) -> None:
        self.sequence = sequence
        self.reindex(validate=validate)

    def reindex(self, *, validate: bool = True) -> None:
        if validate:
            self.sequence.validate()
        self.segment_by_id = {item.id: item for item in self.sequence.segments}
        self.candidate_by_id = {
            item.id: item for item in self.sequence.clip_candidates
        }
        self.marker_by_id = {item.id: item for item in self.sequence.markers}
        self._segment_starts = tuple(
            int(item.timeline_in_ms) for item in self.sequence.segments
        )
        self._segment_index = TemporalIntervalIndex(
            (item.timeline_in_ms, item.timeline_out_ms, item)
            for item in self.sequence.segments
        )
        self._segment_order_by_id = {
            item.id: index for index, item in enumerate(self.sequence.segments)
        }
        self._source_segment_index = TemporalIntervalIndex(
            (item.source_in_ms, item.source_out_ms, item)
            for item in self.sequence.segments
        )
        candidate_entries: list[tuple[int, int, HighlightCandidate]] = []
        for candidate in self.sequence.clip_candidates:
            for segment in self._source_segment_index.query(
                candidate.source_in_ms, candidate.source_out_ms,
            ):
                source_in = max(int(candidate.source_in_ms), int(segment.source_in_ms))
                source_out = min(int(candidate.source_out_ms), int(segment.source_out_ms))
                if source_out <= source_in:
                    continue
                timeline_in = int(segment.timeline_in_ms) + source_in - int(segment.source_in_ms)
                timeline_out = int(segment.timeline_in_ms) + source_out - int(segment.source_in_ms)
                candidate_entries.append((timeline_in, timeline_out, candidate))
        self._candidate_index = TemporalIntervalIndex(candidate_entries)
        self._marker_index = TemporalIntervalIndex(
            (item.time_ms, item.time_ms + 1, item)
            for item in self.sequence.markers
        )
        self.revision += 1

    def segment_at(self, timeline_ms: int) -> VideoSegment | None:
        if not self._segment_starts:
            return None
        value = int(timeline_ms)
        index = bisect.bisect_right(self._segment_starts, value) - 1
        if index < 0:
            return None
        segment = self.sequence.segments[index]
        if segment.timeline_in_ms <= value < segment.timeline_out_ms:
            return segment
        if (
            value == self.sequence.timeline_duration_ms
            and segment.timeline_out_ms == value
        ):
            return segment
        return None

    def segment_for_source(self, source_ms: int) -> VideoSegment | None:
        """Return the first edit-sequence segment containing a source time."""

        value = int(source_ms)
        matches = self._source_segment_index.query(value, value + 1)
        if matches:
            return min(
                matches,
                key=lambda item: self._segment_order_by_id.get(item.id, 1 << 30),
            )
        if self.sequence.segments:
            tail = self.sequence.segments[-1]
            if value == tail.source_out_ms and tail.timeline_out_ms == self.sequence.timeline_duration_ms:
                return tail
        return None

    def visible_segments(self, start_ms: int, end_ms: int) -> tuple[VideoSegment, ...]:
        return self._segment_index.query(start_ms, end_ms)

    def visible_candidates(self, start_ms: int, end_ms: int) -> tuple[HighlightCandidate, ...]:
        seen: set[str] = set()
        result: list[HighlightCandidate] = []
        for item in self._candidate_index.query(start_ms, end_ms):
            if item.id not in seen:
                seen.add(item.id)
                result.append(item)
        return tuple(result)

    def visible_markers(self, start_ms: int, end_ms: int) -> tuple[TimelineMarker, ...]:
        return self._marker_index.query(start_ms, end_ms)


def runtime_of(project: SubtitleProject) -> EditSequenceRuntime:
    runtime = getattr(project, "_edit_sequence_runtime", None)
    if isinstance(runtime, EditSequenceRuntime):
        return runtime
    media = project.media
    payload = getattr(project, "edit_sequence", None)
    if isinstance(payload, Mapping) and (
        payload.get("segments") or payload.get("empty_timeline")
    ):
        sequence = EditSequence.from_dict(payload, media=media)
    else:
        # A brand-new or legacy project has no persisted edit sequence yet.
        # Materialize the same full-source identity sequence as the migration
        # boundary instead of treating the empty mapping as an empty timeline.
        sequence = identity_sequence(media)
        from .studio_media_pool import primary_video_track_id
        primary = next((t for t in project.video_tracks if t.id == primary_video_track_id(project)), None)
        if primary is not None and primary.clips:
            assets = {a.asset_id: a for a in project.media_pool}
            sequence.segments = [VideoSegment(c.id, assets[c.asset_id].canonical_source,
                c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms)
                for c in primary.clips if c.asset_id in assets]
    runtime = EditSequenceRuntime(sequence)
    setattr(project, "_edit_sequence_runtime", runtime)
    return runtime


def sequence_of(project: SubtitleProject) -> EditSequence:
    """Return the canonical runtime sequence without serialization or mutation."""

    return runtime_of(project).sequence


def replace_runtime_sequence(
    project: SubtitleProject,
    sequence: EditSequence,
    *,
    validate: bool = True,
) -> EditSequence:
    runtime = runtime_of(project)
    runtime.replace(sequence, validate=validate)
    return runtime.sequence


def persist_sequence(project: SubtitleProject) -> dict[str, Any]:
    """Explicit runtime -> persisted-schema boundary used by project snapshots."""

    sequence = runtime_of(project).sequence
    sequence.source_path = sequence.source_path or str(project.media.path or "")
    if not sequence.source_duration_ms:
        sequence.source_duration_ms = int(project.media.duration_ms or 0)
    payload = sequence.to_dict()
    setattr(project, "_persisting_edit_sequence", True)
    try:
        project.edit_sequence = payload
    finally:
        setattr(project, "_persisting_edit_sequence", False)
    return payload


def store_sequence(project: SubtitleProject, sequence: EditSequence) -> None:
    """Compatibility write boundary; high-frequency commands use transactions."""

    replace_runtime_sequence(project, sequence, validate=True)
    persist_sequence(project)


def ensure_edit_sequence(project: SubtitleProject) -> EditSequence:
    """Old projects get one full-source segment. Never mutates the media file."""
    existing_runtime = getattr(project, "_edit_sequence_runtime", None)
    if isinstance(existing_runtime, EditSequenceRuntime):
        return existing_runtime.sequence
    payload = getattr(project, "edit_sequence", None)
    if isinstance(payload, Mapping) and (payload.get("segments") or payload.get("empty_timeline")):
        sequence = EditSequence.from_dict(payload, media=project.media)
    else:
        sequence = identity_sequence(project.media)
    setattr(project, "_edit_sequence_runtime", EditSequenceRuntime(sequence))
    # Loading/migration is an explicit persistence boundary.  Ordinary reads
    # after this point never touch ``project.edit_sequence``.
    persist_sequence(project)
    return sequence


def timeline_duration_ms(project: SubtitleProject) -> int:
    sequence = sequence_of(project)
    from .studio_media_pool import media_graph_duration_ms

    return max(
        int(sequence.timeline_duration_ms),
        media_graph_duration_ms(project),
        0,
    )


# ---------------------------------------------------------------------------
# 非破坏式剪辑投影（2026-09-19 P0）。
#
# 历史缺陷：generate_edit/restore_full 通过 remap_cues 物理改写 project.cues
# ——生成剪辑时区间外字幕被丢弃、"返回完整录播"只能映射回幸存子集，且
# 自动保存把片段展示数据写成了完整工程数据（用户实测 496→15 条）。
# 现在 project.cues 永远保持全集+源时间；剪辑序列是纯视图：
# 列表/时间轴/active 高亮/导出走 timeline 域投影，mpv 原生 ASS 走 source
# 域投影（mpv 在 mapped 模式下时钟恒在源域，序列时间事件永不命中=
# "剪辑模式视频无字幕"的根因）。派生 cue id 携带来源段，同一来源片段
# 被使用多次时各实例天然区分。
CUE_DERIVATION_MARK = "#"


def derived_cue_id(cue_id: str, segment_id: str) -> str:
    return f"{cue_id}{CUE_DERIVATION_MARK}{segment_id}"


def is_derived_cue_id(cue_id: str) -> bool:
    return CUE_DERIVATION_MARK in str(cue_id or "")


def source_cue_id_of(cue_id: str) -> str:
    text = str(cue_id or "")
    return text.split(CUE_DERIVATION_MARK, 1)[0] if CUE_DERIVATION_MARK in text else text


def caption_projection_sequence(project):
    """Legacy V1 ownership plus explicitly moved instances, never lane overlap."""
    sequence = sequence_of(project)
    bound = set(project.studio_state.get('caption_bound_clip_ids', []))
    if not bound:
        return sequence
    present = {s.id for s in sequence.segments}
    assets = {a.asset_id: a for a in project.media_pool}
    extra = [VideoSegment(c.id, assets[c.asset_id].canonical_source,
        c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms)
        for track in project.video_tracks for c in track.clips
        if c.id not in present and c.asset_id in assets and
        (c.id in bound or bound.intersection(sequence.segment_lineage.get(c.id, [])))]
    if not extra:
        return sequence
    sequence = copy.deepcopy(sequence)
    sequence.segments.extend(extra)
    sequence.segments.sort(key=lambda s: (s.timeline_in_ms, s.id))
    sequence.empty_timeline = False
    return sequence


def caption_continuous_segments(sequence: EditSequence) -> list[VideoSegment]:
    """Rejoin razor siblings for caption projection, without editing media.

    Integer source milliseconds are the persistence contract. At each seam,
    the union's affine map must round to exactly the stored source cut. This
    accepts the unavoidable integer rounding of a speed-adjusted razor, and
    rejects moved pieces, different rates, and repeated source instances.
    """
    from fractions import Fraction
    from .studio_project import _normalized_media_source
    result = []
    def family(segment):
        ancestry = sequence.segment_lineage.get(segment.id, [])
        return ancestry[-1] if ancestry else segment.id
    groups = []
    for segment in sequence.segments:
        previous = groups[-1][-1] if groups else None
        if (previous is not None and family(previous) == family(segment)
                and _normalized_media_source(previous.source_path or sequence.source_path)
                    == _normalized_media_source(segment.source_path or sequence.source_path)
                and previous.timeline_out_ms == segment.timeline_in_ms
                and previous.source_out_ms == segment.source_in_ms):
            groups[-1].append(segment)
        else:
            groups.append([segment])
    for group in groups:
        first, last = group[0], group[-1]
        union_source = last.source_out_ms - first.source_in_ms
        union_time = last.timeline_out_ms - first.timeline_in_ms
        if all(first.source_in_ms + round(Fraction(
                (piece.timeline_in_ms-first.timeline_in_ms)*union_source, union_time))
                == piece.source_in_ms for piece in group):
            joined = copy.deepcopy(first)
            joined.source_out_ms, joined.timeline_out_ms = last.source_out_ms, last.timeline_out_ms
            result.append(joined)
        else:
            result.extend(copy.deepcopy(group))
    return result


def projected_cues(
    project: SubtitleProject,
    *,
    domain: str = "timeline",
    min_visible_ms: int = 1,
) -> list[StudioCue]:
    """按当前活动序列派生展示 cue（identity 序列零开销直通源列表）。

    domain="timeline"：序列时间（字幕列表/时间轴/active 查询/导出）。
    domain="source"：源时间+按段裁边（mpv 域 native ASS；同一源 cue 在多
    实例中只保留一个事件避免 libass 重影）。
    跨入点/出点的 cue 只在派生结果中裁边，源 cue 永不被修改。
    """
    from .recognition_input import project_recognized_cues
    if project.render_settings.get('_cue_domain') == 'timeline':
        return project.cues
    recognized = project_recognized_cues(project, domain=domain)
    if recognized is not None:
        return recognized
    sequence = caption_projection_sequence(project)
    sequence = copy.copy(sequence)
    sequence.segments = caption_continuous_segments(sequence)
    from .studio_project import _normalized_media_source
    cue_source = _normalized_media_source(project.media.path)
    if sequence.empty_timeline:
        return []
    same_source = all(_normalized_media_source(s.source_path or sequence.source_path) == cue_source
                      for s in sequence.segments)
    if (sequence.is_identity() and same_source) or not sequence.segments:
        return project.cues
    cues = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    output: list[StudioCue] = []
    seen_source: set[str] = set() if domain == "source" else None
    for cue in cues:
        for segment in sequence.segments:
            if _normalized_media_source(segment.source_path or sequence.source_path) != cue_source:
                continue
            overlap_in = max(int(cue.start_ms), int(segment.source_in_ms))
            overlap_out = min(int(cue.end_ms), int(segment.source_out_ms))
            if overlap_out - overlap_in < max(1, int(min_visible_ms)):
                continue
            item = copy.deepcopy(cue)
            item.id = derived_cue_id(cue.id, segment.id)
            if domain == "source":
                item.start_ms, item.end_ms = overlap_in, overlap_out
            else:
                rate = segment.source_duration_ms / max(1, segment.duration_ms)
                item.start_ms = round(segment.timeline_in_ms + (overlap_in-segment.source_in_ms)/rate)
                item.end_ms = round(segment.timeline_in_ms + (overlap_out-segment.source_in_ms)/rate)
            output.append(item)
            if seen_source is not None:
                seen_source.add(str(cue.id))
                break  # source 域同 cue 只留一个（重复段重影防护）
    output.sort(key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    return output


def map_timing_to_source(
    project: SubtitleProject,
    cue: StudioCue,
    start_ms: int,
    end_ms: int,
) -> tuple[int, int] | None:
    """把序列域的计时编辑目标映射回源域；无法无损映射时返回 None。

    源 cue 完整落在单个段内（未被裁边）时按段偏移平移；跨界/被裁边的
    cue 的源计时保持不变（剪辑模式下拖动边界手势对源数据不做半吊子改写）。
    """
    sequence = caption_projection_sequence(project)
    info = project.generation_metadata.get("timeline_recognition")
    if info:
        # Canonical cues in a recognition result use the captured edit clock.
        # Refuse ambiguous timing edits after restructuring the captured edit.
        if sequence.to_dict() == info["sequence"]:
            return int(start_ms), int(end_ms)
        candidates = set()
        from .recognition_input import matching_recognition_segments
        previous = info["sequence"].get("segments", [])
        for old in previous:
            if not (old["timeline_in_ms"] <= cue.start_ms and cue.end_ms <= old["timeline_out_ms"]):
                continue
            old_rate = (old["source_out_ms"]-old["source_in_ms"])/max(1,old["timeline_out_ms"]-old["timeline_in_ms"])
            for seg in matching_recognition_segments(sequence, previous, old):
                if seg.source_path != old["source_path"] or not (seg.timeline_in_ms <= start_ms < end_ms <= seg.timeline_out_ms):
                    continue
                rate = seg.source_duration_ms/max(1,seg.duration_ms)
                a = seg.source_in_ms+(start_ms-seg.timeline_in_ms)*rate
                b = seg.source_in_ms+(end_ms-seg.timeline_in_ms)*rate
                candidates.add((round(old["timeline_in_ms"]+(a-old["source_in_ms"])/old_rate),
                                round(old["timeline_in_ms"]+(b-old["source_in_ms"])/old_rate)))
        if len(candidates) == 1:
            return next(iter(candidates))
        return None
    if sequence.is_identity():
        return int(start_ms), int(end_ms)
    for segment in sequence.segments:
        if (
            int(segment.source_in_ms) <= int(cue.start_ms)
            and int(cue.end_ms) <= int(segment.source_out_ms)
        ):
            rate = segment.source_duration_ms / max(1, segment.duration_ms)
            return (round(segment.source_in_ms + (start_ms-segment.timeline_in_ms)*rate),
                    round(segment.source_in_ms + (end_ms-segment.timeline_in_ms)*rate))
    return None


def segment_at(sequence: EditSequence, timeline_ms: int) -> VideoSegment | None:
    time = int(timeline_ms)
    for segment in sequence.segments:
        if segment.timeline_in_ms <= time < segment.timeline_out_ms:
            return segment
        if time == sequence.timeline_duration_ms and segment.timeline_out_ms == time:
            return segment
    return None


def previous_edit_ms(sequence: EditSequence, playhead_ms: int) -> int | None:
    time = max(0, int(playhead_ms))
    segment = segment_at(sequence, time if time < sequence.timeline_duration_ms else time - 1)
    if segment is None:
        return 0 if time > 0 else None
    if time > segment.timeline_in_ms:
        return segment.timeline_in_ms
    index = sequence.segments.index(segment)
    if index <= 0:
        return None
    return sequence.segments[index - 1].timeline_in_ms


def next_edit_ms(sequence: EditSequence, playhead_ms: int) -> int | None:
    time = max(0, int(playhead_ms))
    if time >= sequence.timeline_duration_ms:
        return None
    segment = segment_at(sequence, time)
    if segment is None:
        return sequence.timeline_duration_ms
    if time < segment.timeline_out_ms:
        return segment.timeline_out_ms
    index = sequence.segments.index(segment)
    if index + 1 >= len(sequence.segments):
        return None
    return sequence.segments[index + 1].timeline_out_ms


def split_at_playhead(sequence: EditSequence, playhead_ms: int) -> EditSequence:
    """Create an edit point. Does not recode or copy media, and does not touch cues."""
    result = copy.deepcopy(sequence)
    time = max(0, min(int(playhead_ms), result.timeline_duration_ms))
    segment = segment_at(result, time if time < result.timeline_duration_ms else time - 1)
    if segment is None:
        return result
    if time <= segment.timeline_in_ms + MIN_SEGMENT_MS or time >= segment.timeline_out_ms - MIN_SEGMENT_MS:
        return result
    from fractions import Fraction
    origin = next((s for s in caption_continuous_segments(result)
        if (s.id == segment.id or s.id in result.segment_lineage.get(segment.id, []))
        and s.timeline_in_ms <= segment.timeline_in_ms < segment.timeline_out_ms <= s.timeline_out_ms), segment)
    source_cut = origin.source_in_ms + round(Fraction(
        (time-origin.timeline_in_ms)*origin.source_duration_ms, origin.duration_ms))
    left = copy.deepcopy(segment)
    right = copy.deepcopy(segment)
    left.source_out_ms = source_cut
    left.timeline_out_ms = time
    right.id = f"seg-{uuid.uuid4().hex[:10]}"
    result.segment_lineage[right.id] = list(dict.fromkeys(
        [segment.id, *result.segment_lineage.get(segment.id, [])]))
    right.source_in_ms = left.source_out_ms
    right.timeline_in_ms = time
    index = result.segments.index(segment)
    result.segments[index:index + 1] = [left, right]
    result.validate()
    result.selected_segment_id = left.id
    return result


def delete_timeline_range(sequence: EditSequence, start_ms: int, end_ms: int) -> EditSequence:
    """Ripple-delete [start, end) on the timeline and close the gap."""
    result = copy.deepcopy(sequence)
    start = max(0, int(start_ms))
    end = max(start + 1, int(end_ms))
    if end - start < MIN_SEGMENT_MS:
        return result
    # Split so delete boundaries land on edit points.
    if segment_at(result, start) and start not in {item.timeline_in_ms for item in result.segments}:
        result = split_at_playhead(result, start)
    if segment_at(result, end) and end not in {item.timeline_in_ms for item in result.segments} | {result.timeline_duration_ms}:
        result = split_at_playhead(result, end)
    result.segments = [
        item for item in result.segments
        if not (item.timeline_in_ms >= start and item.timeline_out_ms <= end)
    ]
    result.empty_timeline = not result.segments
    # Close only the removed interval, preserving all unrelated authored gaps.
    for item in result.segments:
        if item.timeline_in_ms >= end:
            item.timeline_in_ms -= end - start
            item.timeline_out_ms -= end - start
    for name in ('in_point_ms', 'out_point_ms'):
        value = getattr(result, name)
        if value is not None and value >= start:
            setattr(result, name, max(start, value - (end - start)))
    result.validate()
    return result


def delete_segments(sequence: EditSequence, segment_ids: Iterable[str]) -> EditSequence:
    """Ripple-delete selected video segments as one atomic sequence edit."""
    wanted = {str(item) for item in segment_ids if str(item)}
    result = copy.deepcopy(sequence)
    if not wanted:
        return result
    result.segments = [item for item in result.segments if item.id not in wanted]
    result.empty_timeline = not result.segments
    result.selected_segment_id = ""
    result.normalize_timeline()
    return result


def overwrite_insert_segment(
    sequence: EditSequence,
    *,
    source_path: str,
    source_in_ms: int,
    source_out_ms: int,
    at_ms: int,
) -> EditSequence:
    """Overwrite-insert a foreign clip as a main-track segment.

    2026-09-06（四图反馈·图二）：V2 片段拖进主轨（V1）的序列语义——在
    ``at_ms`` 处把 [at, at+duration) 的既有内容替换为外来素材段（Premiere
    overwrite），总时间轴长度不变，后续段右移补位。segment 支持任意
    source_path；主轨 mpv 源切换由多轨预览已有逻辑承载。
    """

    result = copy.deepcopy(sequence)
    source_in = max(0, int(source_in_ms))
    source_out = max(source_in + MIN_SEGMENT_MS, int(source_out_ms))
    duration = source_out - source_in
    start = max(0, min(int(at_ms), max(0, result.timeline_duration_ms)))
    end = start + duration
    # 对齐覆写边界到剪辑点（与 delete_timeline_range 同款 split 手法）。
    if segment_at(result, start) and start not in {item.timeline_in_ms for item in result.segments}:
        result = split_at_playhead(result, start)
    if (
        end < result.timeline_duration_ms
        and segment_at(result, end)
        and end not in {item.timeline_in_ms for item in result.segments}
    ):
        result = split_at_playhead(result, end)
    result.segments = [
        item for item in result.segments
        if not (item.timeline_in_ms >= start and item.timeline_out_ms <= end)
    ]
    # 边界两侧被 split 出来的残余半段若与覆写区部分重叠，裁掉重叠部分。
    trimmed: list[VideoSegment] = []
    for item in result.segments:
        if item.timeline_out_ms > start and item.timeline_in_ms < end:
            overlap_left = max(item.timeline_in_ms, start) - item.timeline_in_ms
            if item.timeline_in_ms < start and overlap_left >= MIN_SEGMENT_MS:
                left = copy.deepcopy(item)
                left.source_out_ms = left.source_in_ms + overlap_left
                left.timeline_out_ms = item.timeline_in_ms + overlap_left
                trimmed.append(left)
            overlap_right = item.timeline_out_ms - min(item.timeline_out_ms, end)
            if item.timeline_out_ms > end and overlap_right >= MIN_SEGMENT_MS:
                right = copy.deepcopy(item)
                right.id = f"seg-{uuid.uuid4().hex[:10]}"
                right.source_in_ms = right.source_in_ms + (
                    min(item.timeline_out_ms, end) - item.timeline_in_ms
                )
                trimmed.append(right)
            continue
        trimmed.append(item)
    result.segments = trimmed
    result.segments.append(
        VideoSegment(
            id=f"seg-{uuid.uuid4().hex[:10]}",
            source_path=str(source_path or ""),
            source_in_ms=source_in,
            source_out_ms=source_out,
            timeline_in_ms=start,
            timeline_out_ms=end,
        )
    )
    result.segments.sort(key=lambda item: (item.timeline_in_ms, item.id))
    result.empty_timeline = not result.segments
    result.normalize_timeline()
    return result


def ripple_cues(
    cues: Sequence[StudioCue],
    start_ms: int,
    end_ms: int,
    *,
    min_duration_ms: int = MIN_CUE_MS,
) -> list[StudioCue]:
    """Keep subtitle times on the *edited* timeline.

    Fully covered cues are dropped. Cues that cross a boundary are clamped.
    Cues after the deleted range shift left by the deleted duration.
    """
    start = max(0, int(start_ms))
    end = max(start, int(end_ms))
    deleted = end - start
    if deleted <= 0:
        return [copy.deepcopy(item) for item in cues]
    kept: list[StudioCue] = []
    for cue in cues:
        item = copy.deepcopy(cue)
        if item.end_ms <= start:
            kept.append(item)
            continue
        if item.start_ms >= end:
            item.start_ms -= deleted
            item.end_ms -= deleted
            if item.end_ms - item.start_ms >= min_duration_ms:
                kept.append(item)
            continue
        if item.start_ms >= start and item.end_ms <= end:
            continue
        if item.start_ms < start:
            item.end_ms = start if item.end_ms <= end else item.end_ms - deleted
        else:
            item.start_ms = start
            item.end_ms -= deleted
        if item.end_ms - item.start_ms >= min_duration_ms:
            item.start_ms = max(0, item.start_ms)
            item.end_ms = max(item.start_ms + min_duration_ms, item.end_ms)
            kept.append(item)
    return kept


def timeline_to_source_range(
    sequence: EditSequence,
    start_ms: int,
    end_ms: int,
) -> list[tuple[int, int]]:
    """Map a timeline range onto one or more source ranges."""
    start = max(0, int(start_ms))
    end = max(start, int(end_ms))
    ranges: list[tuple[int, int]] = []
    for segment in sequence.segments:
        overlap_in = max(start, segment.timeline_in_ms)
        overlap_out = min(end, segment.timeline_out_ms)
        if overlap_out <= overlap_in:
            continue
        source_in = segment.source_in_ms + (overlap_in - segment.timeline_in_ms)
        source_out = segment.source_in_ms + (overlap_out - segment.timeline_in_ms)
        ranges.append((source_in, source_out))
    return ranges


def remap_cues(
    cues: Sequence[StudioCue],
    old_sequence: EditSequence,
    new_sequence: EditSequence,
    *,
    min_duration_ms: int = MIN_CUE_MS,
) -> list[StudioCue]:
    """Move cue times from one edit timeline onto another via source time."""
    kept: list[StudioCue] = []
    for cue in cues:
        source_ranges = timeline_to_source_range(old_sequence, cue.start_ms, cue.end_ms)
        if not source_ranges:
            continue
        source_in = source_ranges[0][0]
        source_out = source_ranges[-1][1]
        new_ranges: list[tuple[int, int]] = []
        for segment in new_sequence.segments:
            overlap_in = max(source_in, segment.source_in_ms)
            overlap_out = min(source_out, segment.source_out_ms)
            if overlap_out <= overlap_in:
                continue
            timeline_in = segment.timeline_in_ms + (overlap_in - segment.source_in_ms)
            timeline_out = segment.timeline_in_ms + (overlap_out - segment.source_in_ms)
            new_ranges.append((timeline_in, timeline_out))
        if not new_ranges:
            continue
        item = copy.deepcopy(cue)
        item.start_ms = new_ranges[0][0]
        item.end_ms = new_ranges[-1][1]
        if item.end_ms - item.start_ms >= min_duration_ms:
            kept.append(item)
    return kept


def sequence_from_candidates(
    media: StudioMedia,
    candidates: Iterable[HighlightCandidate],
    *,
    locked: bool = False,
) -> EditSequence:
    sequence = EditSequence(
        video_track_locked=bool(locked),
        source_path=str(media.path or ""),
        source_duration_ms=int(media.duration_ms or 0),
    )
    for candidate in candidates:
        duration = int(candidate.source_out_ms) - int(candidate.source_in_ms)
        if duration < MIN_SEGMENT_MS:
            continue
        source_in = max(0, int(candidate.source_in_ms))
        source_out = min(sequence.source_duration_ms or source_in + duration, int(candidate.source_out_ms))
        if source_out - source_in < MIN_SEGMENT_MS:
            continue
        sequence.segments.append(
            VideoSegment(
                id=f"seg-{uuid.uuid4().hex[:10]}",
                source_path=sequence.source_path,
                source_in_ms=source_in,
                source_out_ms=source_out,
                timeline_in_ms=0,
                timeline_out_ms=source_out - source_in,
            )
        )
    if not sequence.segments:
        sequence.segments = [identity_segment(sequence.source_path, sequence.source_duration_ms)]
    sequence.normalize_timeline()
    return sequence


def accepted_candidates(sequence: EditSequence) -> list[HighlightCandidate]:
    return [item for item in sequence.clip_candidates if item.status == "accepted"]
