"""Cross-track clip selection and one atomic, rigid group move."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ClipSelection:
    video_ids: set[str] = field(default_factory=set)
    audio_ids: set[str] = field(default_factory=set)
    cue_ids: set[str] = field(default_factory=set)

    @property
    def count(self):
        return len(self.video_ids)+len(self.audio_ids)+len(self.cue_ids)


def expand_linked_selection(project, selection):
    from .studio_clip_edit import video_track_locked
    video = {c.id:(t,c) for t in project.video_tracks for c in t.clips}
    audio = {c.id:(t,c) for t in project.audio_tracks for c in t.clips}
    linked_groups = {g.id for g in project.av_track_groups if g.linked}
    selection.video_ids = {key for key in selection.video_ids if key in video and not video_track_locked(project,video[key][0])}
    blocked_audio={c.id for t,c in audio.values() if c.link_group_id in linked_groups
        and c.linked_video_clip_id in video and video_track_locked(project,video[c.linked_video_clip_id][0])}
    selection.audio_ids = {key for key in selection.audio_ids if key in audio and not audio[key][0].locked and key not in blocked_audio}
    for track, clip in audio.values():
        if clip.link_group_id not in linked_groups or not clip.linked_video_clip_id:
            continue
        if clip.linked_video_clip_id in selection.video_ids and not track.locked:
            selection.audio_ids.add(clip.id)
        if clip.id in selection.audio_ids and clip.linked_video_clip_id in video:
            owner = video[clip.linked_video_clip_id][0]
            if not video_track_locked(project, owner):
                selection.video_ids.add(clip.linked_video_clip_id)
    return selection


def remove_linked_selection(project,selection,media,clip_id):
    """Deselect an editable AV group as the same unit used by its move."""
    getattr(selection,{'video':'video_ids','audio':'audio_ids','subtitle':'cue_ids'}[media]).discard(clip_id)
    if media=='subtitle':return selection
    linked_groups={g.id for g in project.av_track_groups if g.linked}
    audio=[c for t in project.audio_tracks for c in t.clips if c.link_group_id in linked_groups]
    video_id=clip_id if media=='video' else next((c.linked_video_clip_id for c in audio if c.id==clip_id),'')
    if video_id:
        selection.video_ids.discard(video_id)
        selection.audio_ids.difference_update(c.id for c in audio if c.linked_video_clip_id==video_id)
    return selection


def forward_selection(project, start_ms, *, lane=None, locked_speakers=()):
    from .studio_clip_edit import video_track_locked
    from .studio_edit_sequence import projected_cues
    result = ClipSelection()
    start_ms = int(start_ms)
    for track in project.video_tracks:
        if (lane is None or lane == ('video',track.id)) and not video_track_locked(project,track):
            result.video_ids.update(c.id for c in track.clips if c.timeline_out_ms > start_ms)
    for track in project.audio_tracks:
        if (lane is None or lane == ('audio',track.id)) and not track.locked:
            result.audio_ids.update(c.id for c in track.clips if c.timeline_out_ms > start_ms)
    result.cue_ids.update(c.id for c in projected_cues(project) if c.end_ms > start_ms
                          and c.speaker_id not in locked_speakers
                          and (lane is None or lane == ('subtitle',c.speaker_id)))
    # Shift single-track is intentionally literal; linked partners are moved
    # by the edit core, but are not added to another visible lane's selection.
    return expand_linked_selection(project,result) if lane is None else result


def move_selection_command(project, selection, delta_ms, *, page=None, locked_speakers=()):
    from .studio_clip_edit import _working_copy, _finalize_edit, video_track_locked
    from .studio_caption_timeline import ensure_independent_captions, shift_caption
    selection = expand_linked_selection(project,selection)
    working = _working_copy(project)
    ensure_independent_captions(working)
    intervals = [(c.timeline_in_ms,c.timeline_out_ms) for t in working.video_tracks for c in t.clips if c.id in selection.video_ids]
    intervals += [(c.timeline_in_ms,c.timeline_out_ms) for t in working.audio_tracks for c in t.clips if c.id in selection.audio_ids]
    intervals += [(c.start_ms,c.end_ms) for c in working.cues if c.id in selection.cue_ids and c.speaker_id not in locked_speakers]
    if not intervals:
        raise ValueError('没有可移动的未锁定片段')
    delta = max(-min(a for a,b in intervals),int(delta_ms))
    for track in working.video_tracks:
        if video_track_locked(project,track):
            continue
        for clip in track.clips:
            if clip.id in selection.video_ids:
                clip.timeline_in_ms += delta
                clip.timeline_out_ms += delta
    for track in working.audio_tracks:
        if track.locked:
            continue
        for clip in track.clips:
            if clip.id in selection.audio_ids:
                clip.timeline_in_ms += delta
                clip.timeline_out_ms += delta
    for cue in working.cues:
        if cue.id in selection.cue_ids and cue.speaker_id not in locked_speakers:
            shift_caption(working,cue,delta)
    return _finalize_edit(project,working,'移动选中片段',page=page,locked_speakers=locked_speakers)


def delete_selection_command(project, selection, *, page=None, locked_speakers=()):
    from .studio_clip_edit import _working_copy, _finalize_edit, video_track_locked
    selection=expand_linked_selection(project,selection)
    working=_working_copy(project)
    for track in working.video_tracks:
        if not video_track_locked(project,track):
            track.clips=[c for c in track.clips if c.id not in selection.video_ids]
    for track in working.audio_tracks:
        if not track.locked:
            track.clips=[c for c in track.clips if c.id not in selection.audio_ids]
    working.cues=[c for c in working.cues if c.id not in selection.cue_ids or c.speaker_id in locked_speakers]
    return _finalize_edit(project,working,'删除选中片段',page=page,locked_speakers=locked_speakers)


def copy_selection_command(project, selection, delta_ms, *, page=None, locked_speakers=()):
    """Duplicate a rigid selection with fresh IDs and remapped linked audio."""
    import copy
    import uuid
    from .studio_clip_edit import _working_copy, _finalize_edit
    from .studio_caption_timeline import KEY, shift_caption, locked_caption_speakers

    locked_speakers = locked_caption_speakers(project, page, locked_speakers)

    selection = expand_linked_selection(project, copy.deepcopy(selection))
    working = _working_copy(project)
    videos = [(t, c) for t in working.video_tracks for c in t.clips if c.id in selection.video_ids]
    audios = [(t, c) for t in working.audio_tracks for c in t.clips if c.id in selection.audio_ids]
    cues = [c for c in working.cues if c.id in selection.cue_ids and c.speaker_id not in locked_speakers]
    starts = [c.timeline_in_ms for t, c in videos + audios] + [c.start_ms for c in cues]
    if not starts:
        raise ValueError('没有可复制的未锁定片段')
    delta = max(-min(starts), int(delta_ms))
    video_ids = {c.id: f'clip-{uuid.uuid4().hex[:12]}' for t, c in videos}
    copied = ClipSelection()
    for track, clip in videos:
        clone = copy.deepcopy(clip)
        clone.id = video_ids[clip.id]
        clone.timeline_in_ms += delta
        clone.timeline_out_ms += delta
        track.clips.append(clone)
        copied.video_ids.add(clone.id)
    for track, clip in audios:
        clone = copy.deepcopy(clip)
        clone.id = f'audio-{uuid.uuid4().hex[:12]}'
        clone.linked_video_clip_id = video_ids.get(clip.linked_video_clip_id, '')
        if not clone.linked_video_clip_id:
            clone.link_group_id = ''
        clone.timeline_in_ms += delta
        clone.timeline_out_ms += delta
        track.clips.append(clone)
        copied.audio_ids.add(clone.id)
    receipts = working.studio_state.get(KEY, {}).get('instances', {})
    for cue in cues:
        clone = copy.deepcopy(cue)
        clone.id = f'cue-{uuid.uuid4().hex[:12]}'
        if cue.id in receipts:
            receipts[clone.id] = copy.deepcopy(receipts[cue.id])
        shift_caption(working, clone, delta)
        working.cues.append(clone)
        copied.cue_ids.add(clone.id)
    for track in working.video_tracks + working.audio_tracks:
        track.clips.sort(key=lambda c: (c.timeline_in_ms, c.id))
    working.cues.sort(key=lambda c: (c.start_ms, c.id))
    command = _finalize_edit(project, working, '复制选中片段', page=page, locked_speakers=locked_speakers)
    command.copied_selection = copied
    return command
