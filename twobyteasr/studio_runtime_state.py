"""Canonical Studio runtime transactions and scoped state propagation.

This module deliberately has no Qt dependency.  Project/runtime state owns
data and indexes; controllers subscribe to immutable :class:`StateDelta`
values and decide which UI consumers need work.
"""

from __future__ import annotations

import copy
import bisect
import marshal
import re
import warnings
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import IntFlag, auto
from typing import TYPE_CHECKING, Callable, Iterable

from .studio_edit_sequence import EditSequence, sequence_of

if TYPE_CHECKING:
    from .studio_project import StudioCue, SubtitleProject


class DirtyDomain(IntFlag):
    """Typed invalidation domains consumed by Studio controllers/views."""

    NONE = 0
    PROJECT_METADATA = auto()
    SEQUENCE_STRUCTURE = auto()
    CUE_MODEL = auto()
    CUE_CONTENT = auto()
    CUE_TIMING = auto()
    CUE_SELECTION = auto()
    CUE_STYLE = auto()
    TIMELINE_INDEX = auto()
    TIMELINE_PIXELS = auto()
    NATIVE_SUBTITLE = auto()
    ADVANCED_PREVIEW = auto()
    TRANSFORM = auto()
    QC = auto()
    CLIP_STATUS = auto()
    AUTOSAVE = auto()
    MEDIA_POOL = auto()
    VIDEO_TRACKS = auto()
    AUDIO_TRACKS = auto()
    MEDIA_TIMING = auto()
    VIDEO_COMPOSITION = auto()
    AUDIO_GAIN = auto()


SEQUENCE_DOMAINS = (
    DirtyDomain.SEQUENCE_STRUCTURE
    | DirtyDomain.TIMELINE_INDEX
    | DirtyDomain.CLIP_STATUS
)
CUE_DOMAINS = (
    DirtyDomain.CUE_MODEL
    | DirtyDomain.CUE_CONTENT
    | DirtyDomain.CUE_TIMING
    | DirtyDomain.CUE_STYLE
)
STYLE_DOMAINS = DirtyDomain.CUE_STYLE | DirtyDomain.ADVANCED_PREVIEW
MEDIA_DOMAINS = (
    DirtyDomain.MEDIA_POOL
    | DirtyDomain.VIDEO_TRACKS
    | DirtyDomain.AUDIO_TRACKS
    | DirtyDomain.MEDIA_TIMING
    | DirtyDomain.VIDEO_COMPOSITION
)
TRACK_STRUCTURE = DirtyDomain.VIDEO_TRACKS | DirtyDomain.AUDIO_TRACKS


@dataclass(frozen=True, slots=True)
class SegmentState:
    id: str
    source_path: str
    source_in_ms: int
    source_out_ms: int
    timeline_in_ms: int
    timeline_out_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.timeline_out_ms - self.timeline_in_ms)

    @property
    def source_duration_ms(self) -> int:
        return max(0, self.source_out_ms - self.source_in_ms)


@dataclass(frozen=True, slots=True)
class SequenceState:
    """Small immutable sequence snapshot used for edit-context mapping."""

    source_path: str
    source_duration_ms: int
    empty_timeline: bool
    video_track_locked: bool
    segments: tuple[SegmentState, ...]
    lineage: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def segment_lineage(self):
        return dict(self.lineage)

    @property
    def timeline_duration_ms(self) -> int:
        if not self.segments:
            return 0 if self.empty_timeline else int(self.source_duration_ms)
        return int(self.segments[-1].timeline_out_ms)

    @classmethod
    def capture(cls, sequence: EditSequence) -> "SequenceState":
        return cls(
            source_path=str(sequence.source_path),
            source_duration_ms=int(sequence.source_duration_ms),
            empty_timeline=bool(sequence.empty_timeline),
            video_track_locked=bool(sequence.video_track_locked),
            lineage=tuple((key, tuple(value)) for key, value in sequence.segment_lineage.items()),
            segments=tuple(
                SegmentState(
                    id=str(item.id),
                    source_path=str(item.source_path),
                    source_in_ms=int(item.source_in_ms),
                    source_out_ms=int(item.source_out_ms),
                    timeline_in_ms=int(item.timeline_in_ms),
                    timeline_out_ms=int(item.timeline_out_ms),
                )
                for item in sequence.segments
            ),
        )


@dataclass(frozen=True, slots=True)
class StateDelta:
    """One immutable logical state commit delivered to scoped consumers."""

    action_id: str
    dirty: DirtyDomain
    affected_cue_ids: frozenset[str]
    affected_sequence_ids: frozenset[str]
    affected_ranges: tuple[tuple[int, int], ...]
    selection_before: str
    selection_after: str
    revision: int
    sequence_before: SequenceState | None = None
    sequence_after: SequenceState | None = None

    def touches(self, domains: DirtyDomain) -> bool:
        return bool(self.dirty & domains)


DeltaSubscriber = Callable[[StateDelta], None]


def _action_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value or "state_change").lower())
    return cleaned.strip("_") or "state_change"


class ProjectStateRuntime:
    """Project-lifetime cue indexes plus one nested transaction coordinator."""

    def __init__(self, project: "SubtitleProject") -> None:
        self.revision = 0
        self.commit_count = 0
        self.last_delta: StateDelta | None = None
        self.delta_history: list[StateDelta] = []
        self.subscriber_errors: list[str] = []
        self.selected_cue_id = ""
        self._subscribers: list[DeltaSubscriber] = []
        self._active: StateTransaction | None = None
        self._cue_by_id: dict[str, StudioCue] = {}
        self._cue_starts: tuple[int, ...] = ()
        self._cue_order: tuple[str, ...] = ()
        self._cue_prefix_max_end: tuple[int, ...] = ()
        self._sequence_runtime = getattr(project, "_edit_sequence_runtime", None)
        self.reindex_cues(project)

    def __deepcopy__(self, memo):
        clone = object.__new__(type(self))
        memo[id(self)] = clone
        clone.revision = self.revision
        clone.commit_count = self.commit_count
        clone.last_delta = self.last_delta
        clone.delta_history = list(self.delta_history)
        clone.subscriber_errors = []
        clone.selected_cue_id = self.selected_cue_id
        clone._subscribers = []
        clone._active = None
        clone._cue_by_id = {}
        clone._view_by_id = {}
        clone._view_cues = ()
        clone._cue_starts = ()
        clone._cue_order = ()
        clone._cue_prefix_max_end = ()
        clone._cue_ends = ()
        clone._cue_end_order = ()
        clone._sequence_runtime = copy.deepcopy(self._sequence_runtime, memo)
        return clone

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    @property
    def cue_by_id(self) -> dict[str, "StudioCue"]:
        return self._cue_by_id

    def cues_at(self, milliseconds: int) -> tuple["StudioCue", ...]:
        value = int(milliseconds)
        index = bisect.bisect_right(self._cue_starts, value) - 1
        matches: list[StudioCue] = []
        while index >= 0 and self._cue_prefix_max_end[index] > value:
            cue = self._view_by_id[self._cue_order[index]]
            if cue.start_ms <= value < cue.end_ms:
                matches.append(cue)
            index -= 1
        matches.reverse()
        return tuple(matches)

    def visible_cues(self, start_ms: int, end_ms: int) -> tuple["StudioCue", ...]:
        start, end = int(start_ms), int(end_ms)
        stop = bisect.bisect_left(self._cue_starts, end)
        return tuple(
            self._view_by_id[cue_id]
            for cue_id in self._cue_order[:stop]
            if self._view_by_id[cue_id].end_ms > start
        )

    def cues_before(self, milliseconds: int):
        """Nearest completed timeline cues first, without scanning future cues."""
        index = bisect.bisect_right(self._cue_ends, int(milliseconds)) - 1
        while index >= 0:
            yield self._view_by_id[self._cue_end_order[index]]
            index -= 1

    def reindex_cues(self, project: "SubtitleProject") -> None:
        # 2026-09-19 P0：剪辑序列下索引的是"投影视图"（派生 cue，序列
        # 时间）。双映射：_view_by_id 供 cues_at/visible_cues 做序列域
        # 查询；_cue_by_id（对外命令回写入口）把派生 id 解析回源 cue
        # 对象——编辑作用于源数据，投影在事务重建时刷新。
        from .studio_edit_sequence import projected_cues, source_cue_id_of

        view = projected_cues(project, domain="timeline")
        self._view_cues = view
        self._view_by_id = {cue.id: cue for cue in view}
        if view is project.cues:
            self._cue_by_id = dict(self._view_by_id)
        else:
            source_by_id = {cue.id: cue for cue in project.cues}
            self._cue_by_id = dict(source_by_id)
            for cue in view:
                resolved = source_by_id.get(source_cue_id_of(cue.id))
                if resolved is not None:
                    self._cue_by_id[cue.id] = resolved
        ordered = sorted(view, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
        self._cue_order = tuple(str(cue.id) for cue in ordered)
        self._cue_starts = tuple(int(cue.start_ms) for cue in ordered)
        running_end = 0
        prefix: list[int] = []
        for cue in ordered:
            running_end = max(running_end, int(cue.end_ms))
            prefix.append(running_end)
        self._cue_prefix_max_end = tuple(prefix)
        ended = sorted(view, key=lambda cue: (cue.end_ms, cue.start_ms, cue.id))
        self._cue_ends = tuple(int(cue.end_ms) for cue in ended)
        self._cue_end_order = tuple(cue.id for cue in ended)

    @property
    def view_cues(self) -> tuple["StudioCue", ...]:
        """当前活动序列的展示 cue（identity=源列表；剪辑=派生投影）。"""
        return tuple(self._view_cues) if hasattr(self, "_view_cues") else tuple()

    def subscribe(self, callback: DeltaSubscriber) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: DeltaSubscriber) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def transaction(
        self,
        project: "SubtitleProject",
        *,
        action_id: str,
        dirty: DirtyDomain = DirtyDomain.NONE,
        affected_cue_ids: Iterable[str] = (),
        affected_sequence_ids: Iterable[str] = (),
        affected_ranges: Iterable[tuple[int, int]] = (),
        selection_before: str | None = None,
        selection_after: str | None = None,
        snapshot_cues: bool = True,
    ) -> "StateTransaction":
        return StateTransaction(
            self,
            project,
            action_id=_action_id(action_id),
            dirty=dirty,
            affected_cue_ids=affected_cue_ids,
            affected_sequence_ids=affected_sequence_ids,
            affected_ranges=affected_ranges,
            selection_before=selection_before,
            selection_after=selection_after,
            snapshot_cues=snapshot_cues,
        )

    def _emit(self, delta: StateDelta) -> None:
        for subscriber in tuple(self._subscribers):
            try:
                subscriber(delta)
            except Exception as exc:  # state is committed; a UI failure must not corrupt it
                self.subscriber_errors.append(
                    f"{delta.action_id}: {type(exc).__name__}: {exc}"
                )
                warnings.warn(
                    f"Studio state subscriber failed for {delta.action_id}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )


def _json_snapshot(value):
    """Rollback copy of a JSON-shaped project dict (marshal: ~4x deepcopy)."""
    if type(value) in (dict, list):
        try:
            return marshal.loads(marshal.dumps(value))
        except (ValueError, TypeError):
            pass
    return copy.deepcopy(value)


class StateTransaction(AbstractContextManager["StateTransaction"]):
    """Nested-safe, rollback-capable mutation boundary for one user action."""

    def __init__(
        self,
        state: ProjectStateRuntime,
        project: "SubtitleProject",
        *,
        action_id: str,
        dirty: DirtyDomain,
        affected_cue_ids: Iterable[str],
        affected_sequence_ids: Iterable[str],
        affected_ranges: Iterable[tuple[int, int]],
        selection_before: str | None,
        selection_after: str | None,
        snapshot_cues: bool = True,
    ) -> None:
        self.state = state
        self.project = project
        self.action_id = action_id
        self.dirty = DirtyDomain(dirty)
        self.snapshot_cues = bool(snapshot_cues)
        self.affected_cue_ids = {str(item) for item in affected_cue_ids if str(item)}
        self.affected_sequence_ids = {
            str(item) for item in affected_sequence_ids if str(item)
        }
        self.affected_ranges = {
            (max(0, int(start)), max(0, int(end)))
            for start, end in affected_ranges
        }
        self.selection_before = (
            state.selected_cue_id if selection_before is None else str(selection_before)
        )
        self.selection_after = (
            self.selection_before if selection_after is None else str(selection_after)
        )
        self._parent: StateTransaction | None = None
        self._sequence_snapshot: EditSequence | None = None
        self._sequence_before: SequenceState | None = None
        self._cues_snapshot = None
        self._cues_snapshot_is_full = False
        self._styles_snapshot = None
        self._effects_snapshot = None
        self._recipes_snapshot = None
        self._metadata_snapshot = None
        self._media_pool_snapshot = None
        self._video_tracks_snapshot = None
        self._audio_tracks_snapshot = None
        self._av_track_groups_snapshot = None

    def mark_dirty(
        self,
        domains: DirtyDomain,
        *,
        cue_ids: Iterable[str] = (),
        sequence_ids: Iterable[str] = (),
        ranges: Iterable[tuple[int, int]] = (),
    ) -> None:
        target = self._parent or self
        target.affected_cue_ids.update(str(item) for item in cue_ids if str(item))
        target.affected_sequence_ids.update(
            str(item) for item in sequence_ids if str(item)
        )
        target.affected_ranges.update(
            (max(0, int(start)), max(0, int(end))) for start, end in ranges
        )
        target._capture_domains(DirtyDomain(domains))
        target.dirty |= DirtyDomain(domains)

    def __enter__(self) -> "StateTransaction":
        active = self.state._active
        if active is not None:
            self._parent = active
            active.mark_dirty(
                self.dirty,
                cue_ids=self.affected_cue_ids,
                sequence_ids=self.affected_sequence_ids,
                ranges=self.affected_ranges,
            )
            active.selection_after = self.selection_after
            return self
        self.state._active = self
        self._capture_domains(self.dirty)
        return self

    def _capture_domains(self, domains: DirtyDomain) -> None:
        if domains & SEQUENCE_DOMAINS and self._sequence_snapshot is None:
            current = sequence_of(self.project)
            self._sequence_snapshot = copy.deepcopy(current)
            self._sequence_before = SequenceState.capture(current)
        if domains & CUE_DOMAINS:
            # snapshot_cues=False is the splice-command contract: the caller
            # pre-validates every cue it inserts (timing + unique ids) so the
            # post-mutation validation in _validate_and_commit cannot fail,
            # and it owns rollback semantics for its own splice. Skipping the
            # full-list deepcopy here is what keeps O(affected) commands from
            # paying an O(all cues) snapshot on every apply.
            wants_full = bool(domains & DirtyDomain.CUE_MODEL) or not self.affected_cue_ids
            if self.snapshot_cues:
                if self._cues_snapshot is None and wants_full:
                    self._cues_snapshot = copy.deepcopy(self.project.cues)
                    self._cues_snapshot_is_full = True
                elif self._cues_snapshot is None:
                    self._cues_snapshot = {
                        cue.id: copy.deepcopy(cue)
                        for cue in self.project.cues
                        if cue.id in self.affected_cue_ids
                    }
                elif not self._cues_snapshot_is_full:
                    for cue in self.project.cues:
                        if (
                            cue.id in self.affected_cue_ids
                            and cue.id not in self._cues_snapshot
                        ):
                            self._cues_snapshot[cue.id] = copy.deepcopy(cue)
                if wants_full and not self._cues_snapshot_is_full:
                    partial = self._cues_snapshot
                    self._cues_snapshot = [
                        copy.deepcopy(partial.get(cue.id, cue))
                        for cue in self.project.cues
                    ]
                    self._cues_snapshot_is_full = True
        if domains & STYLE_DOMAINS and self._styles_snapshot is None:
            self._styles_snapshot = copy.deepcopy(self.project.styles)
            self._effects_snapshot = copy.deepcopy(self.project.effects)
            self._recipes_snapshot = copy.deepcopy(self.project.style_recipes)
        if domains & DirtyDomain.PROJECT_METADATA and self._metadata_snapshot is None:
            self._metadata_snapshot = (
                copy.deepcopy(self.project.media),
                _json_snapshot(self.project.studio_state),
                _json_snapshot(self.project.generation_metadata),
                _json_snapshot(self.project.render_settings),
            )
        if domains & MEDIA_DOMAINS:
            if self._media_pool_snapshot is None:
                self._media_pool_snapshot = copy.deepcopy(self.project.media_pool)
            if self._video_tracks_snapshot is None:
                self._video_tracks_snapshot = copy.deepcopy(self.project.video_tracks)
            if self._audio_tracks_snapshot is None:
                self._audio_tracks_snapshot = copy.deepcopy(self.project.audio_tracks)
            if self._av_track_groups_snapshot is None:
                self._av_track_groups_snapshot = copy.deepcopy(self.project.av_track_groups)

    def _rollback(self) -> None:
        if self._sequence_snapshot is not None:
            from .studio_edit_sequence import replace_runtime_sequence

            replace_runtime_sequence(
                self.project, copy.deepcopy(self._sequence_snapshot), validate=False
            )
        if self._cues_snapshot is not None:
            if self._cues_snapshot_is_full:
                self.project.cues = copy.deepcopy(self._cues_snapshot)
            else:
                snapshots = self._cues_snapshot
                self.project.cues = [
                    copy.deepcopy(snapshots.get(cue.id, cue))
                    for cue in self.project.cues
                ]
        if self._styles_snapshot is not None:
            self.project.styles = copy.deepcopy(self._styles_snapshot)
            self.project.effects = copy.deepcopy(self._effects_snapshot)
            self.project.style_recipes = copy.deepcopy(self._recipes_snapshot)
        if self._metadata_snapshot is not None:
            (
                self.project.media,
                self.project.studio_state,
                self.project.generation_metadata,
                self.project.render_settings,
            ) = copy.deepcopy(self._metadata_snapshot)
        if self._media_pool_snapshot is not None:
            self.project.media_pool = copy.deepcopy(self._media_pool_snapshot)
        if self._video_tracks_snapshot is not None:
            self.project.video_tracks = copy.deepcopy(self._video_tracks_snapshot)
        if self._audio_tracks_snapshot is not None:
            self.project.audio_tracks = copy.deepcopy(self._audio_tracks_snapshot)
        if self._av_track_groups_snapshot is not None:
            self.project.av_track_groups = copy.deepcopy(self._av_track_groups_snapshot)
        self.state.selected_cue_id = self.selection_before
        self.state.reindex_cues(self.project)

    def _validate_and_commit(self) -> StateDelta:
        if self.dirty & SEQUENCE_DOMAINS:
            from .studio_edit_sequence import runtime_of

            runtime_of(self.project).reindex(validate=True)
        if self.dirty & CUE_DOMAINS:
            targets = (
                [cue for cue in self.project.cues if cue.id in self.affected_cue_ids]
                if self.affected_cue_ids
                else list(self.project.cues)
            )
            for cue in targets:
                cue.validate()
            if (
                self.dirty & DirtyDomain.CUE_MODEL
                and len({cue.id for cue in self.project.cues}) != len(self.project.cues)
            ):
                raise ValueError("duplicate cue id in state transaction")
        if self.dirty & STYLE_DOMAINS:
            for style in self.project.styles:
                style.validate()
            if self.project.style_recipes:
                from .style_recipe import StyleRecipe

                normalized = {}
                for recipe_id, payload in self.project.style_recipes.items():
                    normalized[str(recipe_id)] = StyleRecipe.from_dict(payload).to_dict()
                self.project.style_recipes = normalized
        if self.dirty & DirtyDomain.PROJECT_METADATA:
            self.project.media.validate()
        if self.dirty & MEDIA_DOMAINS:
            from .studio_media_pool import validate_media_graph

            validate_media_graph(self.project)
        if self.dirty & CUE_DOMAINS:
            # Timeline projections are detached copies, including style/text.
            # Updating only the command lookup leaves playback routing on the
            # previous style even when the render revision is already current.
            self.state.reindex_cues(self.project)
        self.state.selected_cue_id = self.selection_after
        self.state.revision += 1
        self.state.commit_count += 1
        sequence_after = None
        if self.dirty & SEQUENCE_DOMAINS:
            sequence_after = SequenceState.capture(sequence_of(self.project))
        return StateDelta(
            action_id=self.action_id,
            dirty=self.dirty,
            affected_cue_ids=frozenset(self.affected_cue_ids),
            affected_sequence_ids=frozenset(self.affected_sequence_ids),
            affected_ranges=tuple(sorted(self.affected_ranges)),
            selection_before=self.selection_before,
            selection_after=self.selection_after,
            revision=self.state.revision,
            sequence_before=self._sequence_before,
            sequence_after=sequence_after,
        )

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._parent is not None:
            return False
        self.state._active = None
        if exc_type is not None:
            self._rollback()
            return False
        try:
            delta = self._validate_and_commit()
        except Exception:
            self._rollback()
            raise
        self.state.last_delta = delta
        self.state.delta_history.append(delta)
        if len(self.state.delta_history) > 128:
            del self.state.delta_history[:-128]
        self.state._emit(delta)
        return False


def state_for(project: "SubtitleProject") -> ProjectStateRuntime:
    state = getattr(project, "_studio_state_runtime", None)
    if not isinstance(state, ProjectStateRuntime):
        state = ProjectStateRuntime(project)
        setattr(project, "_studio_state_runtime", state)
    current_sequence_runtime = getattr(project, "_edit_sequence_runtime", None)
    if state._sequence_runtime is not current_sequence_runtime:
        sequence_of(project)
        state._sequence_runtime = getattr(project, "_edit_sequence_runtime", None)
    if set(state.cue_by_id) != {cue.id for cue in project.cues}:
        state.reindex_cues(project)
    return state


def notify_legacy_if_unbound(
    project: "SubtitleProject", callback: Callable[..., None] | None, *args
) -> None:
    """Compatibility adapter for non-Studio callers that still pass callbacks."""

    if callback is not None and not state_for(project).has_subscribers:
        callback(*args)
