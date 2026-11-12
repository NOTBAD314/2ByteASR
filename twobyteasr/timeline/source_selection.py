"""Source monitor selections and atomic, non-ripple media insertion.

All intervals are half open milliseconds. Audio stream indices are audio
ordinals (FFmpeg a:N), not container stream indices or mpv track ids.
"""
from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QUndoCommand

from ..projects.studio_project import AudioClip, AudioTrack, VideoClip, sync_linked_av_contract
from ..projects.studio_runtime_state import DirtyDomain as D, state_for
from .studio_edit_sequence import VideoSegment, sequence_of, replace_runtime_sequence
from .studio_media_pool import asset_by_id, create_video_track, primary_video_track_id, validate_media_graph

SOURCE_MIME = 'application/x-2byteasr-source-selection'


def source_capabilities(asset):
    video = asset.video_metadata.get('has_video')
    if video is None:
        video = Path(asset.canonical_source).suffix.lower() not in {
            '.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma'}
    audio = asset.audio_metadata.get('has_audio', not str(asset.canonical_source).lower().endswith('.gif'))
    return bool(video), bool(audio)


def source_state(project, asset_id):
    return project.studio_state.setdefault('source_monitor', {}).setdefault(asset_id, {})


def source_boundary(asset, value):
    """Nearest representable video frame boundary, preserving the real tail."""
    duration = max(0, int(asset.duration_ms))
    value = max(0, min(duration, int(value)))
    fps = float(asset.video_metadata.get('fps') or 0)
    if source_capabilities(asset)[0] and math.isfinite(fps) and fps > 0 and value < duration:
        value = round(round(value * fps / 1000) * 1000 / fps)
    return max(0, min(duration, value))


@dataclass(frozen=True)
class SourceSelection:
    asset_id: str
    source_in_ms: int
    source_out_ms: int
    mode: str
    stream_index: int = 0

    @property
    def duration_ms(self):
        return self.source_out_ms - self.source_in_ms

    @classmethod
    def capture(cls, project, asset_id, mode='auto'):
        asset = asset_by_id(project, asset_id)
        state = source_state(project, asset_id)
        video, audio = source_capabilities(asset)
        mode = ('av' if video and audio else 'video' if video else 'audio') if mode == 'auto' else mode
        selection = cls(asset_id, source_boundary(asset, state.get('in_ms') or 0),
                        source_boundary(asset, asset.duration_ms if state.get('out_ms') is None else state['out_ms']),
                        mode, int(state.get('stream_index') or 0))
        selection.validate(project)
        return selection

    def validate(self, project):
        asset = asset_by_id(project, self.asset_id)
        video, audio = source_capabilities(asset)
        if self.mode not in {'av', 'video', 'audio'}:
            raise ValueError('未知的素材加入方式')
        if self.mode in {'av', 'video'} and not video or self.mode in {'av', 'audio'} and not audio:
            raise ValueError('素材不包含所选的视频或音频流')
        if not 0 <= self.source_in_ms < self.source_out_ms <= asset.duration_ms:
            raise ValueError('请设置有效的入出点；入点必须早于出点并在素材时长内')
        streams = asset.audio_metadata.get('streams', [])
        if self.stream_index < 0 or streams and self.stream_index >= len(streams):
            raise ValueError('所选音频流已不存在，请重新选择')
        if asset.offline or not Path(asset.canonical_source).is_file():
            raise ValueError('素材文件缺失，请在媒体池重新定位')


def _available(track, start, end):
    if track.locked:
        raise ValueError(f'轨道 {track.id} 已锁定，请选择其他轨道或先解锁')
    if any(c.timeline_in_ms < end and start < c.timeline_out_ms for c in track.clips):
        raise ValueError(f'轨道 {track.id} 的落点与已有片段重叠，请调整位置或选择其他轨道')


def plan_source_insert(project, selection, position_ms, video_target='new', audio_target='new'):
    """Read-only validation used by both drag feedback and the commit boundary."""
    selection.validate(project)
    start = max(0, int(position_ms)); end = start + selection.duration_ms
    video = audio = None
    if selection.mode in {'av', 'video'} and video_target != 'new':
        video = next((t for t in project.video_tracks if t.id == video_target), None)
        if video is None:
            raise ValueError('请选择视频轨道，或选择「新建视频轨」')
        _available(video, start, end)
        from .studio_clip_edit import video_track_locked
        if video_track_locked(project, video):
            raise ValueError(f'轨道 {video.id} 已锁定，请先解锁')
    if selection.mode == 'av' and video:
        group = next((g for g in project.av_track_groups if g.video_track_id == video.id), None)
        if group and not group.linked:
            raise ValueError('该视频轨已解除音视频关联，请选择其他轨或新建关联轨')
        audio_target = group.audio_track_id if group else 'new'
    if selection.mode in {'av', 'audio'} and audio_target != 'new':
        audio = next((t for t in project.audio_tracks if t.id == audio_target), None)
        if audio is None:
            raise ValueError('请选择音频轨道，或选择「新建音频轨」')
        _available(audio, start, end)
    return dict(start_ms=start, end_ms=end, video_track_id=video.id if video else 'new',
                audio_track_id=audio.id if audio else 'new', mode=selection.mode)


class SourceInsertCommand(QUndoCommand):
    """One compact graph/sequence transaction; subtitles are never re-timed."""
    def __init__(self, project, selection, position_ms, video_target='new', audio_target='new'):
        super().__init__('加入源素材选段')
        self.project = project
        self.placement = plan_source_insert(project, selection, position_ms, video_target, audio_target)
        self.before = self._snapshot(project)
        working = copy.copy(project)
        for name in ('media_pool','video_tracks', 'audio_tracks', 'av_track_groups'):
            setattr(working, name, copy.deepcopy(getattr(project, name)))
        from ..projects.project_snapshot import copy_json_value
        from .studio_edit_sequence import EditSequenceRuntime
        working.studio_state = copy_json_value(project.studio_state)
        working._edit_sequence_runtime = EditSequenceRuntime(copy.deepcopy(sequence_of(project)))
        self.caption_before = self.caption_after = None
        if selection.mode in {'av', 'video'} and video_target == primary_video_track_id(project):
            from .studio_caption_timeline import ensure_independent_captions, KEY
            from .studio_edit_sequence import EditSequenceRuntime
            working.cues = copy.deepcopy(project.cues)
            working.render_settings = copy.deepcopy(project.render_settings)
            working._edit_sequence_runtime = EditSequenceRuntime(copy.deepcopy(sequence_of(project)))
            if ensure_independent_captions(working):
                self.caption_before = (copy.deepcopy(project.cues), project.render_settings.get('_cue_domain'),
                                       copy.deepcopy(project.studio_state.get(KEY)))
                self.caption_after = (copy.deepcopy(working.cues), 'timeline', copy.deepcopy(working.studio_state[KEY]))
        start, end = self.placement['start_ms'], self.placement['end_ms']
        video = None
        if selection.mode in {'av', 'video'}:
            video = (create_video_track(working, synchronize=False) if video_target == 'new'
                     else next(t for t in working.video_tracks if t.id == video_target))
            video_clip = VideoClip('clip-' + uuid.uuid4().hex[:12], selection.asset_id,
                selection.source_in_ms, selection.source_out_ms, start, end,
                audio_enabled=selection.mode == 'av')
            video.clips.append(video_clip)
            sync_linked_av_contract(working)
        if selection.mode == 'av':
            group = next(g for g in working.av_track_groups if g.video_track_id == video.id)
            audio = next(t for t in working.audio_tracks if t.id == group.audio_track_id)
            next(c for c in audio.clips if c.linked_video_clip_id == video_clip.id).stream_index = selection.stream_index
        elif selection.mode == 'audio':
            if audio_target == 'new':
                number = 1
                while any(t.id == f'A{number}' for t in working.audio_tracks):
                    number += 1
                audio = AudioTrack(f'A{number}', f'A{number}', z_index=len(working.audio_tracks))
                working.audio_tracks.append(audio)
            else:
                audio = next(t for t in working.audio_tracks if t.id == audio_target)
            audio.clips.append(AudioClip('audio-' + uuid.uuid4().hex[:12], selection.asset_id,
                selection.source_in_ms, selection.source_out_ms, start, end, stream_index=selection.stream_index))
        validate_media_graph(working)
        sequence = copy.deepcopy(sequence_of(project))
        primary = next((t for t in working.video_tracks if t.id == primary_video_track_id(working)), None)
        if primary and video is not None and video.id == primary.id:
            sequence.segments = [VideoSegment(c.id, asset_by_id(working, c.asset_id).canonical_source,
                c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms) for c in primary.clips]
            sequence.empty_timeline = not sequence.segments
            sequence.video_track_locked = primary.locked
        elif primary is None:
            sequence.segments = []
            sequence.empty_timeline = True
        sequence.validate()
        self.after = self._snapshot(working, sequence)
        self.placement.update(video_track_id=video.id if video else '',
                              audio_track_id=audio.id if selection.mode in {'av', 'audio'} else '')

    @staticmethod
    def _snapshot(project, sequence=None):
        return tuple(copy.deepcopy(getattr(project, key)) for key in
                     ('video_tracks', 'audio_tracks', 'av_track_groups')) + (copy.deepcopy(sequence or sequence_of(project)),)

    def _apply(self, snapshot, captions):
        videos, audios, groups, sequence = copy.deepcopy(snapshot)
        dirty = D.TIMELINE_PIXELS | D.AUTOSAVE
        if videos != self.project.video_tracks:
            dirty |= D.VIDEO_TRACKS | D.MEDIA_TIMING | D.VIDEO_COMPOSITION
        if audios != self.project.audio_tracks or groups != self.project.av_track_groups:
            dirty |= D.AUDIO_TRACKS | D.MEDIA_TIMING
        sequence_changed = sequence != sequence_of(self.project)
        if sequence_changed:
            dirty |= D.SEQUENCE_STRUCTURE | D.TIMELINE_INDEX | D.MEDIA_TIMING
        if captions is not None:
            dirty |= D.CUE_MODEL | D.CUE_TIMING | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.PROJECT_METADATA
        with state_for(self.project).transaction(self.project, action_id='source_insert', dirty=dirty,
                snapshot_cues=captions is not None):
            self.project.video_tracks, self.project.audio_tracks, self.project.av_track_groups = videos, audios, groups
            if sequence_changed:replace_runtime_sequence(self.project, sequence)
            if captions is not None:
                cues, domain, receipt = copy.deepcopy(captions)
                self.project.cues = cues
                if domain is None:
                    self.project.render_settings.pop('_cue_domain', None)
                else:
                    self.project.render_settings['_cue_domain'] = domain
                if receipt is None:
                    self.project.studio_state.pop('caption_timeline', None)
                else:
                    self.project.studio_state['caption_timeline'] = receipt

    def redo(self):
        self._apply(self.after, self.caption_after)

    def undo(self):
        self._apply(self.before, self.caption_before)
