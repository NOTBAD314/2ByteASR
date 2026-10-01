"""Undoable media-pool and multi-track project commands."""

from __future__ import annotations

import copy
from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from .studio_project import SubtitleProject
from .studio_runtime_state import DirtyDomain, state_for


MediaMutation = Callable[[SubtitleProject], None]


def _video_timing_signature(tracks) -> tuple:
    return tuple(
        (
            str(track.id),
            tuple(
                (
                    str(clip.id),
                    int(clip.timeline_in_ms),
                    int(clip.timeline_out_ms),
                    int(clip.source_in_ms),
                    int(clip.source_out_ms),
                    float(getattr(clip, "playback_rate", 1.0) or 1.0),
                )
                for clip in track.clips
            ),
        )
        for track in tracks
    )


def _video_composition_signature(tracks) -> tuple:
    return tuple(
        (
            str(track.id),
            int(track.z_index),
            bool(track.enabled),
            tuple(
                (
                    str(clip.id),
                    str(clip.asset_id),
                    bool(clip.enabled),
                    repr(getattr(clip, "transform", None)),
                )
                for clip in track.clips
            ),
        )
        for track in tracks
    )


class MediaGraphCommand(QUndoCommand):
    """Replace only the small media graph, never the cue/style project body."""

    def __init__(
        self,
        project: SubtitleProject,
        after_pool,
        after_tracks,
        after_audio_tracks,
        after_av_track_groups,
        text: str,
        after_state=None,
    ) -> None:
        super().__init__(str(text))
        self.project = project
        self.before_pool = copy.deepcopy(project.media_pool)
        self.before_tracks = copy.deepcopy(project.video_tracks)
        self.before_audio_tracks = copy.deepcopy(project.audio_tracks)
        self.before_av_track_groups = copy.deepcopy(project.av_track_groups)
        self.after_pool = copy.deepcopy(after_pool)
        self.after_tracks = copy.deepcopy(after_tracks)
        self.after_audio_tracks = copy.deepcopy(after_audio_tracks)
        self.after_av_track_groups = copy.deepcopy(after_av_track_groups)
        after_state = project.studio_state if after_state is None else after_state
        keys = {key for key in project.studio_state.keys() | after_state.keys()
                if project.studio_state.get(key) != after_state.get(key)}
        self.before_state = {key: copy.deepcopy(project.studio_state[key]) for key in keys if key in project.studio_state}
        self.after_state = {key: copy.deepcopy(after_state[key]) for key in keys if key in after_state}
        self.state_keys = keys

    def _apply(self, media_pool, video_tracks, audio_tracks, av_track_groups, state=None) -> None:
        pool_changed = media_pool != self.project.media_pool
        tracks_changed = video_tracks != self.project.video_tracks
        audio_tracks_changed = (
            audio_tracks != self.project.audio_tracks
            or av_track_groups != self.project.av_track_groups
        )
        dirty = DirtyDomain.AUTOSAVE | DirtyDomain.TIMELINE_PIXELS
        if self.state_keys:dirty |= DirtyDomain.VIDEO_TRACKS
        if pool_changed:
            dirty |= DirtyDomain.MEDIA_POOL
        old_sources = {asset.asset_id: asset.canonical_source for asset in self.project.media_pool}
        relinks = {asset.asset_id: asset.canonical_source for asset in media_pool
                   if asset.asset_id in old_sources and old_sources[asset.asset_id] != asset.canonical_source}
        if relinks:
            dirty |= DirtyDomain.MEDIA_TIMING | DirtyDomain.VIDEO_COMPOSITION | DirtyDomain.SEQUENCE_STRUCTURE
        if tracks_changed:
            dirty |= DirtyDomain.VIDEO_TRACKS
            if _video_timing_signature(video_tracks) != _video_timing_signature(
                self.project.video_tracks
            ):
                # Timing changes can change the visible base at the current
                # project time, so cached composition ownership is stale too.
                dirty |= DirtyDomain.MEDIA_TIMING | DirtyDomain.VIDEO_COMPOSITION
            if _video_composition_signature(video_tracks) != _video_composition_signature(
                self.project.video_tracks
            ):
                dirty |= DirtyDomain.VIDEO_COMPOSITION
        if audio_tracks_changed:
            dirty |= DirtyDomain.AUDIO_TRACKS
        from .studio_edit_sequence import sequence_of
        from .studio_media_pool import primary_video_track_id

        sequence = sequence_of(self.project)
        primary_id = primary_video_track_id(self.project)
        primary_track = next(
            (track for track in video_tracks if track.id == primary_id),
            None,
        )
        primary_clips = {clip.id: clip.asset_id for clip in primary_track.clips} if primary_track else {}
        primary_asset_id = next((clip.asset_id for clip in primary_track.clips
                                 if old_sources.get(clip.asset_id) == self.project.media.path), '') if primary_track else ''
        target_primary_lock = (
            bool(primary_track.locked)
            if primary_track is not None
            else bool(sequence.video_track_locked)
        )
        if bool(sequence.video_track_locked) != target_primary_lock:
            dirty |= DirtyDomain.SEQUENCE_STRUCTURE
        with state_for(self.project).transaction(
            self.project,
            action_id=self.text(),
            dirty=dirty,
        ):
            self.project.media_pool = copy.deepcopy(media_pool)
            self.project.video_tracks = copy.deepcopy(video_tracks)
            self.project.audio_tracks = copy.deepcopy(audio_tracks)
            self.project.av_track_groups = copy.deepcopy(av_track_groups)
            for key in self.state_keys:
                if key in (state or {}):self.project.studio_state[key] = copy.deepcopy(state[key])
                else:self.project.studio_state.pop(key, None)
            if relinks:
                self.project.media.path = relinks.get(primary_asset_id, self.project.media.path)
                primary_asset=next((a for a in self.project.media_pool if a.asset_id==primary_asset_id and a.asset_id in relinks),None)
                if primary_asset:
                    self.project.media.duration_ms=primary_asset.duration_ms
                    self.project.media.width=int(primary_asset.video_metadata.get('width') or 0)
                    self.project.media.height=int(primary_asset.video_metadata.get('height') or 0)
                    self.project.media.fingerprint=primary_asset.fingerprint
                    self.project.media.display_name=primary_asset.display_name
                sequence.source_path = relinks.get(primary_asset_id, sequence.source_path)
                for segment in sequence.segments:
                    segment.source_path = relinks.get(primary_clips.get(segment.id), segment.source_path)
            sequence_of(self.project).video_track_locked = target_primary_lock

    def redo(self) -> None:
        self._apply(
            self.after_pool,
            self.after_tracks,
            self.after_audio_tracks,
            self.after_av_track_groups,
            self.after_state,
        )

    def undo(self) -> None:
        self._apply(
            self.before_pool,
            self.before_tracks,
            self.before_audio_tracks,
            self.before_av_track_groups,
            self.before_state,
        )


def media_graph_command(
    project: SubtitleProject,
    text: str,
    mutate: MediaMutation,
) -> MediaGraphCommand:
    """Build one command by mutating an isolated copy of the media graph."""

    working = copy.copy(project)
    working.media_pool = copy.deepcopy(project.media_pool)
    working.video_tracks = copy.deepcopy(project.video_tracks)
    working.audio_tracks = copy.deepcopy(project.audio_tracks)
    working.av_track_groups = copy.deepcopy(project.av_track_groups)
    working.studio_state = copy.deepcopy(project.studio_state)
    mutate(working)
    return MediaGraphCommand(
        project,
        working.media_pool,
        working.video_tracks,
        working.audio_tracks,
        working.av_track_groups,
        text,
        after_state=working.studio_state,
    )


class CompositeMediaCommand(QUndoCommand):
    """One undo step over pre-built child commands.

    2026-09-06（四图反馈·图二）：V1↔V2 跨轨拖拽同时改 EditSequence 与
    video_tracks——两个域各有专属命令（EditSequenceCommand / media_graph），
    组合命令让用户按一次 Ctrl+Z 完整回退。子命令必须先构建（各自的 before
    快照在构建时捕获），redo 按序、undo 逆序。
    """

    def __init__(self, text: str, children: list[QUndoCommand]) -> None:
        super().__init__(str(text))
        self._children = [item for item in children if item is not None]

    def redo(self) -> None:
        for command in self._children:
            command.redo()

    def undo(self) -> None:
        for command in reversed(self._children):
            command.undo()


class AudioMasterCommand(QUndoCommand):
    """Set or cancel the exclusive Audio Master track.

    2026-09-06（四图反馈·图二）：``mode="mix_all"`` 表示取消唯一 master
    （皇冠再点一次）——全部未静音轨混音输出。undo 恢复原 (track, mode)。
    """

    def __init__(self, project: SubtitleProject, track_id: str, *, mode: str = "manual") -> None:
        from .studio_media_pool import audio_master_mode, audio_master_track_id, track_by_id

        mode = str(mode or "manual")
        if mode == "manual":
            track_by_id(project, str(track_id))
        super().__init__(
            "取消 Audio Master（全轨混音）" if mode == "mix_all" else "设置 Audio Master Track"
        )
        self.project = project
        self.before_mode = audio_master_mode(project)
        # mix_all 态下 audio_master_track_id() 返回空；undo 回 manual 时需要
        # 恢复的是 studio_state 里仍保存的原始轨，故先切回 raw 读取。
        self.before_track = self._raw_master(project)
        self.after_mode = mode
        self.after_track = str(track_id) if mode == "manual" else self._raw_master(project)

    @staticmethod
    def _raw_master(project: SubtitleProject) -> str:
        return str(project.studio_state.get("audio_master_track_id") or "")

    def _apply(self, track_id: str, mode: str) -> None:
        from .studio_media_pool import set_audio_master_mode, set_audio_master_track

        with state_for(self.project).transaction(
            self.project,
            action_id=self.text(),
            dirty=DirtyDomain.AUTOSAVE | DirtyDomain.VIDEO_TRACKS,
        ):
            if track_id:
                set_audio_master_track(self.project, track_id)
            set_audio_master_mode(self.project, mode)

    def redo(self) -> None:
        self._apply(self.after_track, self.after_mode)

    def undo(self) -> None:
        self._apply(self.before_track, self.before_mode)
