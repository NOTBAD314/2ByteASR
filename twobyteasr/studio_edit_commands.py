"""Undo commands for video-track razor / ripple / generate / restore."""

from __future__ import annotations

import copy
import inspect
from typing import Callable

from PySide6.QtGui import QUndoCommand

from .studio_edit_sequence import (
    EditSequence,
    HighlightCandidate,
    TimelineMarker,
    accepted_candidates,
    delete_segments,
    delete_timeline_range,
    ensure_edit_sequence,
    identity_sequence,
    next_edit_ms,
    previous_edit_ms,
    remap_cues,
    ripple_cues,
    sequence_from_candidates,
    sequence_of,
    split_at_playhead,
    replace_runtime_sequence,
)
from .studio_project import StudioCue, SubtitleProject
from .studio_runtime_state import (
    DirtyDomain,
    notify_legacy_if_unbound,
    state_for,
)


ChangedCallback = Callable[..., None]


def _mapping_signature(sequence: EditSequence) -> tuple[tuple[object, ...], ...]:
    """Collapse split-only boundaries into one source/timeline mapping shape."""

    merged: list[list[object]] = []
    for item in sequence.segments:
        row: list[object] = [
            str(item.source_path),
            int(item.source_in_ms),
            int(item.source_out_ms),
            int(item.timeline_in_ms),
            int(item.timeline_out_ms),
        ]
        if merged:
            previous = merged[-1]
            contiguous = (
                previous[0] == row[0]
                and previous[2] == row[1]
                and previous[4] == row[3]
            )
            if contiguous:
                previous[2] = row[2]
                previous[4] = row[4]
                continue
        merged.append(row)
    if not merged and not sequence.empty_timeline:
        merged.append([
            str(sequence.source_path),
            0,
            int(sequence.source_duration_ms),
            0,
            int(sequence.source_duration_ms),
        ])
    return tuple(tuple(item) for item in merged)


def _clip_status_signature(sequence: EditSequence) -> tuple[object, ...]:
    """Return only the sequence state consumed by the Clip Assistant panel."""

    return (
        tuple(sequence.clip_candidates),
        sequence.in_point_ms,
        sequence.out_point_ms,
        str(sequence.danmaku_path),
    )


def _notify_changed(
    changed: ChangedCallback | None,
    before: EditSequence,
    after: EditSequence,
) -> None:
    if changed is None:
        return
    try:
        parameters = tuple(inspect.signature(changed).parameters.values())
    except (TypeError, ValueError):
        parameters = ()
    accepts_pair = len(parameters) >= 2 or any(
        item.kind is inspect.Parameter.VAR_POSITIONAL for item in parameters
    )
    if accepts_pair:
        changed(copy.deepcopy(before), copy.deepcopy(after))
    else:
        changed()


class EditSequenceCommand(QUndoCommand):
    """One undo step covering the video sequence and every affected cue."""

    def __init__(
        self,
        project: SubtitleProject,
        after_sequence: EditSequence,
        after_cues: list[StudioCue] | None = None,
        text: str = "Edit video",
        changed: ChangedCallback | None = None,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.before_sequence = copy.deepcopy(sequence_of(project))
        self.after_sequence = copy.deepcopy(after_sequence)
        # Sequence-only operations (Razor, marker/lock changes, no-op deletes)
        # must not retain and clone the entire cue list twice per undo command.
        # ``None`` is an explicit structural-sharing marker: _apply leaves the
        # project's canonical cues untouched on both redo and undo.
        cues_changed = after_cues is not None and after_cues != project.cues
        self.before_cues = copy.deepcopy(project.cues) if cues_changed else None
        self.after_cues = copy.deepcopy(after_cues) if cues_changed else None
        self.changed = changed

    def _apply(self, sequence: EditSequence, cues: list[StudioCue] | None) -> None:
        before = copy.deepcopy(sequence_of(self.project))
        after = copy.deepcopy(sequence)
        if cues is None:
            affected_cues: set[str] = set()
        else:
            before_cue_map = {cue.id: cue for cue in self.project.cues}
            after_cue_map = {cue.id: cue for cue in cues}
            affected_cues = {
                cue_id for cue_id in set(before_cue_map) | set(after_cue_map)
                if before_cue_map.get(cue_id) != after_cue_map.get(cue_id)
            }
        affected_segments = {
            item.id for item in before.segments
        } | {item.id for item in after.segments}
        ranges = {
            (item.timeline_in_ms, item.timeline_out_ms)
            for item in (*before.segments, *after.segments)
        }
        mapping_changed = _mapping_signature(before) != _mapping_signature(after)
        clip_status_changed = _clip_status_signature(before) != _clip_status_signature(after)
        primary_track_changed = (
            before.video_track_locked != after.video_track_locked
            or before.segments != after.segments
        )
        dirty = (
            DirtyDomain.SEQUENCE_STRUCTURE
            | DirtyDomain.TIMELINE_INDEX
            | DirtyDomain.TIMELINE_PIXELS
            | DirtyDomain.AUTOSAVE
        )
        if clip_status_changed:
            dirty |= DirtyDomain.CLIP_STATUS
        if primary_track_changed:
            dirty |= (
                DirtyDomain.MEDIA_POOL
                | DirtyDomain.VIDEO_TRACKS
                | DirtyDomain.AUDIO_TRACKS
            )
        # A Razor boundary changes V1 structure but not timeline-to-source
        # mapping or subtitle pixels. Rebuilding/writing/reloading the entire
        # ASS and rescanning cue QC here only creates a delayed interaction tail.
        if mapping_changed or affected_cues:
            dirty |= DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.QC
        if affected_cues:
            dirty |= DirtyDomain.CUE_MODEL | DirtyDomain.CUE_TIMING
        state = state_for(self.project)
        selection_after = state.selected_cue_id
        if cues is not None and selection_after and selection_after not in after_cue_map:
            order = [cue.id for cue in cues]
            selection_after = order[0] if order else ""
        with state.transaction(
            self.project,
            action_id=self.text(),
            dirty=dirty,
            affected_cue_ids=affected_cues,
            affected_sequence_ids=affected_segments,
            affected_ranges=ranges,
            selection_after=selection_after,
        ):
            replace_runtime_sequence(self.project, after, validate=False)
            if primary_track_changed:
                from .studio_media_pool import sync_primary_video_track_from_sequence

                sync_primary_video_track_from_sequence(self.project, after)
            if cues is not None:
                self.project.cues = copy.deepcopy(cues)
        if not state.has_subscribers:
            _notify_changed(self.changed, before, copy.deepcopy(after))

    def redo(self) -> None:
        self._apply(self.after_sequence, self.after_cues)

    def undo(self) -> None:
        self._apply(self.before_sequence, self.before_cues)


def razor_video_command(
    project: SubtitleProject,
    playhead_ms: int,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    before = sequence_of(project)
    after = split_at_playhead(before, playhead_ms)
    return EditSequenceCommand(project, after, project.cues, "拆分视频", changed)


def ripple_trim_command(
    project: SubtitleProject,
    edge: str,
    playhead_ms: int,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    sequence = sequence_of(project)
    if edge == "start":
        left = previous_edit_ms(sequence, playhead_ms)
        right = int(playhead_ms)
        label = "Q 波纹修剪到播放头"
    else:
        left = int(playhead_ms)
        right = next_edit_ms(sequence, playhead_ms)
        label = "W 波纹修剪到下一剪辑点"
    if left is None or right is None or right - left < 1:
        return EditSequenceCommand(project, sequence, project.cues, label, changed)
    after_sequence = delete_timeline_range(sequence, left, right)
    # Both source cues and recognition-result cues retain their authored clock.
    # projected_cues owns the conversion through the edited sequence.
    return EditSequenceCommand(project, after_sequence, None, label, changed)


def set_video_lock_command(
    project: SubtitleProject,
    locked: bool,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    sequence = copy.deepcopy(sequence_of(project))
    sequence.video_track_locked = bool(locked)
    label = "锁定视频轨" if locked else "解锁视频轨"
    return EditSequenceCommand(project, sequence, project.cues, label, changed)


def delete_video_segments_command(
    project: SubtitleProject,
    segment_ids: list[str],
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    before = sequence_of(project)
    if before.video_track_locked:
        return EditSequenceCommand(project, before, None, "删除视频片段", changed)
    after = delete_segments(before, segment_ids)
    # 非破坏式（2026-09-19 P0）：字幕由活动序列投影，删除段内的字幕
    # 自然从视图消失，源全集保持不变。
    return EditSequenceCommand(project, after, None, "删除视频片段", changed)


def generate_edit_command(
    project: SubtitleProject,
    candidates: list[HighlightCandidate] | None = None,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    current = sequence_of(project)
    wanted = candidates if candidates is not None else accepted_candidates(current)
    after = sequence_from_candidates(project.media, wanted, locked=current.video_track_locked)
    after.clip_candidates = copy.deepcopy(current.clip_candidates)
    after.markers = copy.deepcopy(current.markers)
    after.danmaku_path = current.danmaku_path
    # 2026-09-19 P0：非破坏式——project.cues 保持全集+源时间，剪辑只是
    # 视图投影（列表/时间轴/ASS/导出按活动序列派生）。此前 remap_cues
    # 物理丢弃区间外字幕，"返回完整录播"永远只能拿回幸存子集，且自动
    # 保存把片段子集写成了完整工程数据（用户实测 496→15 条）。
    return EditSequenceCommand(project, after, None, "根据候选生成剪辑", changed)


def restore_full_sequence_command(
    project: SubtitleProject,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    current = sequence_of(project)
    after = identity_sequence(project.media)
    after.video_track_locked = current.video_track_locked
    after.clip_candidates = copy.deepcopy(current.clip_candidates)
    after.markers = copy.deepcopy(current.markers)
    after.danmaku_path = current.danmaku_path
    # 同上：非破坏式。全集从未离开 project.cues，恢复即切回 identity 视图。
    info = project.generation_metadata.get("timeline_recognition")
    original_cues = None
    if info:
        original_cues = [StudioCue(**row) for row in info.get("original_cues", [])]
    command = EditSequenceCommand(project, after, original_cues, "返回完整录播", changed)
    if info:
        from .studio_project import StudioSpeaker

        class RestoreRecognitionSource(QUndoCommand):
            def __init__(self):
                super().__init__("返回完整录播")
                self.speakers = copy.deepcopy(project.speakers)

            def redo(self):
                project.generation_metadata.pop("timeline_recognition", None)
                project.speakers = [StudioSpeaker(**s) for s in info.get("original_speakers", [])]
                command.redo()

            def undo(self):
                project.generation_metadata["timeline_recognition"] = copy.deepcopy(info)
                project.speakers = copy.deepcopy(self.speakers)
                command.undo()

        return RestoreRecognitionSource()
    return command


def replace_candidates_command(
    project: SubtitleProject,
    candidates: list[HighlightCandidate],
    text: str = "更新剪辑候选",
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    sequence = copy.deepcopy(sequence_of(project))
    # 2026-09-19 P1：重新分析不得丢掉用户已做的取舍——同时间范围（重叠
    # 过半）的旧候选 status/origin 延续到新候选，未匹配的按新结果。
    def _overlap(a: HighlightCandidate, b: HighlightCandidate) -> bool:
        shared = max(0, min(a.source_out_ms, b.source_out_ms) - max(a.source_in_ms, b.source_in_ms))
        shorter = min(a.source_out_ms - a.source_in_ms, b.source_out_ms - b.source_in_ms)
        return shorter > 0 and shared * 2 >= shorter

    for fresh in candidates:
        old = next((item for item in sequence.clip_candidates if _overlap(item, fresh)), None)
        if old is not None and old.status in {"accepted", "ignored"}:
            fresh.status = old.status
            if old.origin == "manual":
                fresh.origin = "manual"
    sequence.clip_candidates = copy.deepcopy(candidates)
    return EditSequenceCommand(project, sequence, None, text, changed)


def add_marker_command(
    project: SubtitleProject,
    marker: TimelineMarker,
    changed: ChangedCallback | None = None,
) -> EditSequenceCommand:
    sequence = copy.deepcopy(sequence_of(project))
    sequence.markers.append(marker)
    return EditSequenceCommand(project, sequence, project.cues, "添加标记", changed)


def ensure_project_sequence(project: SubtitleProject) -> EditSequence:
    return ensure_edit_sequence(project)
