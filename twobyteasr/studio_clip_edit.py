"""Atomic video-lane edits over the existing graph and primary sequence.

Times are integer project milliseconds. Source cues are never rewritten;
their existing instance/lineage projection follows the edited primary graph.
Independent lanes do not participate in a lane-local ripple.
"""
from __future__ import annotations

import copy
import uuid
from fractions import Fraction

from PySide6.QtGui import QUndoCommand

from .studio_edit_sequence import EditSequenceRuntime, VideoSegment, sequence_of, replace_runtime_sequence
from .studio_media_pool import primary_video_track_id, track_by_id, asset_by_id
from .studio_project import sync_linked_av_contract
from .studio_runtime_state import DirtyDomain as D, state_for


def _rate(clip):
    return Fraction(str(clip.playback_rate or 1.0))


def trim_bounds(clip, asset_duration):
    rate = _rate(clip)
    return (max(0, clip.timeline_in_ms - int(Fraction(clip.source_in_ms) / rate)),
            clip.timeline_out_ms + int(Fraction(max(0, asset_duration - clip.source_out_ms)) / rate))


def lane_gap(project, track_id, time_ms):
    """Only bounded leading/interior gaps; never the infinite tail viewport."""
    cursor = 0
    for clip in sorted(track_by_id(project, track_id).clips, key=lambda c: (c.timeline_in_ms, c.id)):
        if cursor <= time_ms < clip.timeline_in_ms:
            return cursor, clip.timeline_in_ms
        if clip.timeline_in_ms <= time_ms < clip.timeline_out_ms:
            return None
        cursor = max(cursor, clip.timeline_out_ms)
    return None


def _editable(project, track_id):
    track = track_by_id(project, track_id)
    if track.locked or (track.id == primary_video_track_id(project) and sequence_of(project).video_track_locked):
        raise ValueError(f'{track.name or track.id} 轨道已锁定，请先解锁')
    for group in project.av_track_groups:
        if group.linked and group.video_track_id == track_id:
            sound = next((a for a in project.audio_tracks if a.id == group.audio_track_id), None)
            if sound and sound.locked:
                raise ValueError(f'关联音轨 {sound.name or sound.id} 已锁定，请先解锁')
    return track


def video_track_locked(project, track):
    return bool(track.locked or (track.id == primary_video_track_id(project)
                                and sequence_of(project).video_track_locked))


def _working_copy(project):
    working = copy.copy(project)
    working.studio_state = copy.deepcopy(project.studio_state)
    working.video_tracks, working.audio_tracks, working.av_track_groups, sequence = _snapshot(project)
    # Older hydration may have materialized a clip ID independently from the
    # captured edit-sequence ID. Prove ownership BEFORE changing geometry;
    # after a razor the right child's ancestry cannot recover that relation.
    from .studio_project import _normalized_media_source
    primary = next((t for t in working.video_tracks if t.id == primary_video_track_id(project)), None)
    if primary:
        for clip in primary.clips:
            source = _normalized_media_source(asset_by_id(project,clip.asset_id).canonical_source)
            matches = [s for s in sequence.segments
                if _normalized_media_source(s.source_path or sequence.source_path) == source
                and (s.source_in_ms,s.source_out_ms,s.timeline_in_ms,s.timeline_out_ms)
                    == (clip.source_in_ms,clip.source_out_ms,clip.timeline_in_ms,clip.timeline_out_ms)]
            if len(matches)==1 and matches[0].id != clip.id:
                origin = matches[0].id
                sequence.segment_lineage[clip.id] = list(dict.fromkeys([
                    *sequence.segment_lineage.get(clip.id, []), origin,
                    *sequence.segment_lineage.get(origin, [])]))
    working._edit_sequence_runtime = EditSequenceRuntime(sequence)
    return working


def _finalize_edit(project, working, label, *, page=None, playhead_after=None,
                   locked_speakers=(), changed=None):
    """Validate the complete result, including changes made by AV materialization."""
    sequence = sequence_of(working)
    primary_id = primary_video_track_id(working)
    primary = next((t for t in working.video_tracks if t.id == primary_id), None)
    if primary:
        sequence.segments = [VideoSegment(c.id, asset_by_id(working, c.asset_id).canonical_source,
            c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms) for c in primary.clips]
        sequence.empty_timeline = not sequence.segments
        sequence.video_track_locked = primary.locked
    sequence.validate()
    working._edit_sequence_runtime.reindex()
    sync_linked_av_contract(working)
    for original in project.video_tracks:
        after = track_by_id(working, original.id)
        if original != after:
            _editable(project, original.id)
            _check_collisions(original, after)
    sounds = {t.id: t for t in working.audio_tracks}
    for original in project.audio_tracks:
        if original.locked and original != sounds.get(original.id):
            raise ValueError(f'关联音轨 {original.name or original.id} 已锁定，请先解锁')
    from .studio_edit_sequence import timeline_duration_ms
    duration = timeline_duration_ms(working)
    for name in ('in_point_ms', 'out_point_ms'):
        value = getattr(sequence, name)
        if value is not None:
            setattr(sequence, name, min(max(0, value), duration))
    if sequence.in_point_ms is not None and sequence.out_point_ms is not None and sequence.out_point_ms <= sequence.in_point_ms:
        sequence.in_point_ms = sequence.out_point_ms = None
    locked = set(locked_speakers) | (set(page.timeline.locked_speakers) if page else set())
    if locked and _locked_caption_ranges(project, locked) != _locked_caption_ranges(working, locked):
        raise ValueError('关联字幕轨道已锁定，请先解锁；此次编辑未提交')
    return ClipEditCommand(project, working, label, page, playhead_after, changed)


def playhead_edit_command(project, action, time_ms, *, page=None, locked_speakers=()):
    """Keyboard scope is all unlocked video lanes, independent of UI selection."""
    point = int(time_ms)
    tracks = [t for t in project.video_tracks if not video_track_locked(project, t)]
    clips = [c for t in tracks for c in t.clips]
    if action == 'split':
        targets = [(t.id, c.id) for t in tracks for c in t.clips
                   if c.timeline_in_ms < point < c.timeline_out_ms]
        if not targets:
            raise ValueError('播放头没有可切开的未锁定视频片段，或已在剪辑边界')
        working = _working_copy(project)
        for track_id, clip_id in targets:
            _editable(project, track_id)
            track = track_by_id(working, track_id)
            _split(working, track, next(c for c in track.clips if c.id == clip_id), point)
            track.clips.sort(key=lambda c: (c.timeline_in_ms, c.id))
        return _finalize_edit(project, working, '拆分视频片段', page=page,
                              locked_speakers=locked_speakers)
    if action not in {'ripple_start', 'ripple_end'}:
        raise ValueError('未知播放头编辑操作')
    covered = any(c.timeline_in_ms <= point < c.timeline_out_ms or
                  (action == 'ripple_start' and c.timeline_in_ms < point == c.timeline_out_ms) for c in clips)
    if not covered:
        raise ValueError('播放头没有可编辑的视频片段；锁定轨道保持原位')
    boundaries = {v for c in clips for v in (c.timeline_in_ms, c.timeline_out_ms)}
    if action == 'ripple_start':
        start, end = max((v for v in boundaries if v < point), default=point), point
    else:
        start, end = point, min((v for v in boundaries if v > point), default=point)
    if end <= start:
        raise ValueError('播放头已在剪辑边界')
    return ripple_ranges_command(project, [(start, end)], page=page,
        locked_speakers=locked_speakers,
        label=f'{"Q" if action == "ripple_start" else "W"} 波纹删除 {start / 1000:.3f}–{end / 1000:.3f} 秒')


def merge_ranges(ranges):
    merged = []
    for a, b in sorted((max(0, int(a)), int(b)) for a, b in ranges if int(b) > max(0, int(a))):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def ripple_ranges_command(project, ranges, *, page=None, locked_speakers=(), label='压缩口播停顿'):
    ranges = merge_ranges(ranges)
    if not ranges:
        raise ValueError('没有可删除的有效区间')
    working = _working_copy(project)
    track_ids = [t.id for t in project.video_tracks if not video_track_locked(project, t)]
    if not track_ids:
        raise ValueError('视频轨道均已锁定，请先解锁')
    point = int(page.timeline.playhead_ms) if page else None
    sequence = sequence_of(working)
    # Descending original-time intervals keep every yet-to-apply timestamp valid.
    for a, b in reversed(ranges):
        for track_id in track_ids:
            track = track_by_id(working, track_id)
            if not any(c.timeline_out_ms > a for c in track.clips):
                continue
            _editable(project, track_id)
            for clip in list(track.clips):
                if clip.timeline_in_ms < a < clip.timeline_out_ms:
                    _split(working, track, clip, a)
            for clip in list(track.clips):
                if clip.timeline_in_ms < b < clip.timeline_out_ms:
                    _split(working, track, clip, b)
            track.clips = [c for c in track.clips if not (a <= c.timeline_in_ms and c.timeline_out_ms <= b)]
            for clip in track.clips:
                if clip.timeline_in_ms >= b:
                    _shift(clip, a - b)
            track.clips.sort(key=lambda c: (c.timeline_in_ms, c.id))
        def close_time(value):
            return value if value < a else a if value < b else value - (b - a)
        if point is not None:
            point = close_time(point)
        if primary_video_track_id(working) in track_ids:
            for name in ('in_point_ms', 'out_point_ms'):
                value = getattr(sequence, name)
                if value is not None:
                    setattr(sequence, name, close_time(value))
    return _finalize_edit(project, working, label, page=page, playhead_after=point,
                          locked_speakers=locked_speakers)


def reassign_clips_command(project, source_track_id, target_track_id, clip_ids, *,
                           start=None, append=False, page=None, locked_speakers=()):
    source = _editable(project, source_track_id)
    target = _editable(project, target_track_id)
    ids = set(clip_ids)
    selected = [c for c in source.clips if c.id in ids]
    if not selected or {c.id for c in selected} != ids:
        raise ValueError('所选片段已改变，请重新选择')
    origin = min(c.timeline_in_ms for c in selected)
    start = max((c.timeline_out_ms for c in target.clips if c.id not in ids), default=0) if append else int(start)
    if start < 0:
        raise ValueError('片段不能移动到负时间')
    working = _working_copy(project)
    source, target = track_by_id(working, source_track_id), track_by_id(working, target_track_id)
    if source_track_id == primary_video_track_id(project) and target_track_id != source_track_id:
        # Record proven instance ownership before it leaves the legacy V1 view.
        working.studio_state['caption_bound_clip_ids'] = sorted(set(
            working.studio_state.get('caption_bound_clip_ids', [])) | ids)
    moving = [c for c in source.clips if c.id in ids]
    source.clips = [c for c in source.clips if c.id not in ids]
    for clip in moving:
        _shift(clip, start - origin)
    target.clips.extend(moving)
    target.clips.sort(key=lambda c: (c.timeline_in_ms, c.id))
    if source_track_id != target_track_id:
        groups = {g.video_track_id: g for g in working.av_track_groups}
        source_group, target_group = groups.get(source_track_id), groups.get(target_track_id)
        if source_group and source_group.linked:
            if not target_group or not target_group.linked:
                raise ValueError('目标轨道音频已解除链接，无法保持原音视频关系')
            source_audio = next(t for t in working.audio_tracks if t.id == source_group.audio_track_id)
            target_audio = next(t for t in working.audio_tracks if t.id == target_group.audio_track_id)
            audio_clips = [c for c in source_audio.clips if c.linked_video_clip_id in ids]
            source_audio.clips = [c for c in source_audio.clips if c.linked_video_clip_id not in ids]
            for clip in audio_clips:
                clip.link_group_id = target_group.id
            target_audio.clips.extend(audio_clips)
    return _finalize_edit(project, working, '移到 V1 并接在末尾' if append else '视频片段换轨',
                          page=page, locked_speakers=locked_speakers)


def preview_clip_edit(project, drag, locked_speakers=()):
    """Use the commit preflight without publishing state or touching undo history.

    The returned snapshot owns both video and audio geometry. Source peaks and
    decoded media are deliberately absent: they remain in their existing caches.
    """
    source = drag['track_id']
    target = drag.get('target_track_id') or source
    ids = set(drag.get('group_intervals', {})) | {drag['clip_id']}
    if drag['mode'] == 'move' and target != source:
        earliest = min((a for a, b in drag.get('group_intervals', {}).values()), default=drag['origin_in'])
        command = reassign_clips_command(project, source, target, ids,
            start=drag['preview_in'] - (drag['origin_in'] - earliest), locked_speakers=locked_speakers)
    else:
        command = clip_edit_command(project, source, 'move' if drag['mode'] == 'move' else 'trim',
            clip_id=drag['clip_id'], clip_ids=ids, start=drag['preview_in'], end=drag['preview_out'],
            locked_speakers=locked_speakers)
    return command.after


def _trim(clip, start, end, asset_duration):
    low, high = trim_bounds(clip, asset_duration)
    start, end = int(start), int(end)
    if start < low or end > high or end <= start:
        raise ValueError('裁切超出可用素材范围或片段时长为空')
    # Interpolate inside the two committed endpoints, avoiding cumulative
    # half-millisecond rounding when repeatedly trimming a speed-adjusted clip.
    # Restoration outside those endpoints uses the unchanged requested rate.
    rate = Fraction(clip.source_out_ms-clip.source_in_ms, clip.timeline_out_ms-clip.timeline_in_ms)
    source_start = clip.source_in_ms + round((start - clip.timeline_in_ms) * (rate if start >= clip.timeline_in_ms else _rate(clip)))
    source_end = clip.source_out_ms + round((end - clip.timeline_out_ms) * (rate if end <= clip.timeline_out_ms else _rate(clip)))
    if not 0 <= source_start < source_end <= asset_duration:
        raise ValueError('裁切超出可用素材范围')
    clip.source_in_ms, clip.source_out_ms = source_start, source_end
    clip.timeline_in_ms, clip.timeline_out_ms = start, end


def _shift(clip, delta):
    clip.timeline_in_ms += delta
    clip.timeline_out_ms += delta


def _split(project, track, clip, time_ms):
    if not clip.timeline_in_ms < time_ms < clip.timeline_out_ms:
        raise ValueError('切点必须位于片段内部')
    sequence = sequence_of(project)
    # Retain the original affine map across successive razors. Interpolating
    # an already rounded child introduces a second source-ms rounding shift.
    from .studio_edit_sequence import caption_continuous_segments
    lane_sequence = copy.copy(sequence)
    lane_sequence.segments = [VideoSegment(c.id, asset_by_id(project, c.asset_id).canonical_source,
        c.source_in_ms,c.source_out_ms,c.timeline_in_ms,c.timeline_out_ms)
        for c in sorted(track.clips,key=lambda c:(c.timeline_in_ms,c.id))]
    origin = next((s for s in caption_continuous_segments(lane_sequence)
        if (s.id == clip.id or s.id in sequence.segment_lineage.get(clip.id, []))
        and s.timeline_in_ms <= clip.timeline_in_ms < clip.timeline_out_ms <= s.timeline_out_ms
        and s.source_in_ms <= clip.source_in_ms < clip.source_out_ms <= s.source_out_ms), clip)
    source = origin.source_in_ms + round(Fraction((time_ms-origin.timeline_in_ms) *
        (origin.source_out_ms-origin.source_in_ms), origin.timeline_out_ms-origin.timeline_in_ms))
    if not clip.source_in_ms < source < clip.source_out_ms:
        raise ValueError('切点过于贴近片段边界')
    right = copy.deepcopy(clip)
    right.id = 'clip-' + uuid.uuid4().hex[:12]
    right.source_in_ms, right.timeline_in_ms = source, time_ms
    clip.source_out_ms, clip.timeline_out_ms = source, time_ms
    sequence.segment_lineage[right.id] = list(dict.fromkeys([clip.id, *sequence.segment_lineage.get(clip.id, [])]))
    track.clips.append(right)
    # Keep per-clip audio settings when materializing the right linked half.
    for group in project.av_track_groups:
        if not group.linked or group.video_track_id != track.id:
            continue
        sound = next((a for a in project.audio_tracks if a.id == group.audio_track_id), None)
        if sound:
            original = next((a for a in sound.clips if a.linked_video_clip_id == clip.id), None)
            if original:
                sibling = copy.deepcopy(original)
                sibling.id = 'audio-' + uuid.uuid4().hex[:12]
                sibling.linked_video_clip_id = right.id
                sound.clips.append(sibling)
    return right


def _check_collisions(before, after):
    old = {c.id: c for c in before.clips}
    clips = sorted(after.clips, key=lambda c: (c.timeline_in_ms, c.id))
    for i, clip in enumerate(clips):
        if clip.timeline_in_ms < 0 or clip.timeline_out_ms <= clip.timeline_in_ms:
            raise ValueError('片段时间范围无效')
        for other in clips[i + 1:]:
            if other.timeline_in_ms >= clip.timeline_out_ms:
                break
            a, b = old.get(clip.id), old.get(other.id)
            previous = max(0, min(a.timeline_out_ms, b.timeline_out_ms) - max(a.timeline_in_ms, b.timeline_in_ms)) if a and b else 0
            overlap = min(clip.timeline_out_ms, other.timeline_out_ms) - max(clip.timeline_in_ms, other.timeline_in_ms)
            if overlap > previous:
                raise ValueError('同轨已有片段，不能重叠；请先移开或裁切')


def _snapshot(project):
    return (copy.deepcopy(project.video_tracks), copy.deepcopy(project.audio_tracks),
            copy.deepcopy(project.av_track_groups), copy.deepcopy(sequence_of(project)))


def _locked_caption_ranges(project, speakers):
    from .studio_edit_sequence import projected_cues, source_cue_id_of
    # Merge contiguous split projections: a harmless razor is not a retime.
    result = {}
    for cue in projected_cues(project):
        if cue.speaker_id in speakers:
            result.setdefault(source_cue_id_of(cue.id), []).append((cue.start_ms, cue.end_ms))
    for key, ranges in result.items():
        merged = []
        for a, b in sorted(ranges):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        result[key] = merged
    return result


class ClipEditCommand(QUndoCommand):
    def __init__(self, project, after, label, page=None, playhead_after=None, changed=None):
        super().__init__(label)
        self.project, self.page, self.changed = project, page, changed
        self.before, self.after = _snapshot(project), _snapshot(after)
        self.before_bindings = copy.deepcopy(project.studio_state.get('caption_bound_clip_ids'))
        self.after_bindings = copy.deepcopy(after.studio_state.get('caption_bound_clip_ids'))
        self.selection = {name: copy.deepcopy(getattr(page.timeline, name)) for name in (
            'selected_video_track_id', 'selected_video_clip_id', 'selected_segment_id', 'selected_segment_ids') } if page else {}
        self.playhead_before = int(page.timeline.playhead_ms) if page else None
        self.playhead_after = playhead_after

    def _apply(self, snapshot, playhead, bindings):
        project = self.project
        before_sequence = copy.deepcopy(sequence_of(project))
        dirty = (D.VIDEO_TRACKS | D.AUDIO_TRACKS | D.MEDIA_TIMING | D.VIDEO_COMPOSITION |
                 D.SEQUENCE_STRUCTURE | D.TIMELINE_INDEX | D.TIMELINE_PIXELS |
                 D.CUE_TIMING | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.AUTOSAVE)
        page = self.page
        if page:
            page._defer_clip_edit_seek = True
        try:
            with state_for(project).transaction(project, action_id=self.text(), dirty=dirty):
                videos, audios, groups, sequence = copy.deepcopy(snapshot)
                project.video_tracks, project.audio_tracks, project.av_track_groups = videos, audios, groups
                if bindings is None:
                    project.studio_state.pop('caption_bound_clip_ids', None)
                else:
                    project.studio_state['caption_bound_clip_ids'] = copy.deepcopy(bindings)
                replace_runtime_sequence(project, sequence)
            if not state_for(project).has_subscribers and self.changed:
                self.changed(before_sequence, copy.deepcopy(sequence_of(project)))
        finally:
            if page:
                page._defer_clip_edit_seek = False
        page = self.page
        if page and page.project is project:
            from .studio_edit_sequence import timeline_duration_ms
            page.timeline.selected_gap = None
            for name, value in self.selection.items():
                setattr(page.timeline, name, copy.deepcopy(value))
            ids = {c.id for t in project.video_tracks for c in t.clips}
            page.timeline.selected_segment_ids.intersection_update(ids)
            if page.timeline.selected_video_clip_id not in ids:
                page.timeline.selected_video_clip_id = ''
            if page.timeline.selected_segment_id not in ids:
                page.timeline.selected_segment_id = ''
            owner = next((t for t in project.video_tracks if any(c.id == page.timeline.selected_video_clip_id for c in t.clips)), None)
            if owner:
                page.timeline.selected_video_track_id = owner.id
            page.timeline.refresh_media_graph()
            target = min(max(0, int(page.timeline.playhead_ms if playhead is None else playhead)), timeline_duration_ms(project))
            page.timeline.set_playhead(target)
            # A razor leaves the media frame intact. For any timing edit the
            # graph/clock must be resubmitted even when the project time stays.
            if self.text() != '拆分视频片段':
                page._seek(target / 1000.0)

    def redo(self):
        self._apply(self.after, self.playhead_after, self.after_bindings)

    def undo(self):
        self._apply(self.before, self.playhead_before, self.before_bindings)


def clip_edit_command(project, track_id, action, *, clip_id='', start=None, end=None,
                      time_ms=None, page=None, locked_speakers=(), changed=None, clip_ids=()):
    """Preflight all linked locks and collisions before publishing one change."""
    original_track = _editable(project, track_id)
    working = copy.copy(project)
    working.video_tracks, working.audio_tracks, working.av_track_groups, sequence = _snapshot(project)
    working._edit_sequence_runtime = EditSequenceRuntime(sequence)
    track = track_by_id(working, track_id)
    clip = next((c for c in track.clips if c.id == clip_id), None)
    removed = None
    playhead_after = int(page.timeline.playhead_ms) if page else None
    if action == 'gap':
        gap = lane_gap(working, track_id, int(start))
        if gap != (int(start), int(end)):
            raise ValueError('所选空白已改变，请重新选择')
        removed = gap
    else:
        if clip is None:
            raise ValueError('目标片段已不存在，请重新选择')
        if action == 'move':
            if int(start) < 0:
                raise ValueError('片段不能移动到负时间')
            delta = int(start) - clip.timeline_in_ms
            for item in track.clips:
                if item.id in set(clip_ids) | {clip.id}:
                    _shift(item, delta)
        elif action == 'trim':
            _trim(clip, start, end, asset_by_id(working, clip.asset_id).duration_ms)
        elif action == 'split':
            _split(working, track, clip, int(time_ms))
        elif action in {'ripple_start', 'ripple_end'}:
            point = int(time_ms)
            if not clip.timeline_in_ms <= point <= clip.timeline_out_ms:
                raise ValueError('播放头不在目标片段内，未波纹裁切')
            removed = (clip.timeline_in_ms, point) if action == 'ripple_start' else (point, clip.timeline_out_ms)
            if removed[0] == removed[1]:
                raise ValueError('播放头已在剪辑边界')
            if removed == (clip.timeline_in_ms, clip.timeline_out_ms):
                track.clips.remove(clip)
            else:
                a, b = (point, clip.timeline_out_ms) if action == 'ripple_start' else (clip.timeline_in_ms, point)
                _trim(clip, a, b, asset_by_id(working, clip.asset_id).duration_ms)
        else:
            raise ValueError(f'未知编辑操作：{action}')
    if removed:
        a, b = removed
        for item in track.clips:
            if item.timeline_in_ms >= b:
                _shift(item, a - b)
        def close_time(value):
            return value if value < a else a if value < b else value - (b - a)
        if playhead_after is not None:
            playhead_after = close_time(playhead_after)
        # Range markers are project-time values; adjust for the edited primary
        # only. Secondary-lane ripple does not retime unrelated project marks.
        if track_id == primary_video_track_id(working):
            for name in ('in_point_ms', 'out_point_ms'):
                value = getattr(sequence, name)
                if value is not None:
                    setattr(sequence, name, close_time(value))
    track.clips.sort(key=lambda c: (c.timeline_in_ms, c.id))
    _check_collisions(original_track, track)
    if track_id == primary_video_track_id(working):
        sequence.segments = [VideoSegment(c.id, asset_by_id(working, c.asset_id).canonical_source,
            c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms) for c in track.clips]
        sequence.empty_timeline = not sequence.segments
        sequence.video_track_locked = track.locked
    sequence.validate()
    working._edit_sequence_runtime.reindex()
    sync_linked_av_contract(working)
    from .studio_edit_sequence import timeline_duration_ms
    duration = timeline_duration_ms(working)
    for name in ('in_point_ms', 'out_point_ms'):
        value = getattr(sequence, name)
        if value is not None:
            setattr(sequence, name, min(max(0, value), duration))
    if sequence.in_point_ms is not None and sequence.out_point_ms is not None and sequence.out_point_ms <= sequence.in_point_ms:
        sequence.in_point_ms = sequence.out_point_ms = None
    locked = set(locked_speakers) | (set(page.timeline.locked_speakers) if page else set())
    if locked and _locked_caption_ranges(project, locked) != _locked_caption_ranges(working, locked):
        raise ValueError('关联字幕轨道已锁定，请先解锁；此次编辑未提交')
    labels = {'move':'移动视频片段', 'trim':'裁切视频边缘', 'split':'拆分视频片段',
              'ripple_start':'Q 波纹裁切片段前部', 'ripple_end':'W 波纹裁切片段后部', 'gap':'删除轨道间隙'}
    return ClipEditCommand(project, working, labels[action], page, playhead_after, changed)
