"""Resolve one rigid displacement against stationary project geometry."""
from .studio_edit_sequence import projected_cues, sequence_of


def snap_group_delta(project, selection, delta, *, playhead, threshold, held=None):
    moving, stationary, lanes = [], [(0, '时间轴零点'), (playhead, '播放头')], []
    for tracks, ids in ((project.video_tracks, selection.video_ids),
                        (project.audio_tracks, selection.audio_ids)):
        for track in tracks:
            selected, fixed = [], []
            for clip in track.clips:
                interval = (clip.timeline_in_ms, clip.timeline_out_ms)
                if clip.id in ids:
                    moving.extend(interval)
                    selected.append(interval)
                else:
                    stationary.extend((value, f'{track.id} 片段边界') for value in interval)
                    fixed.append(interval)
            lanes.append((selected, fixed))
    for cue in projected_cues(project):
        if cue.id in selection.cue_ids:
            moving.extend((cue.start_ms, cue.end_ms))
        else:
            stationary.extend(((cue.start_ms, '字幕开头'), (cue.end_ms, '字幕结尾')))
    stationary.extend((m.time_ms, f'标记 {m.label}') for m in sequence_of(project).markers)
    minimum = min(moving, default=0)
    delta = max(-minimum, int(delta))
    choices = []
    for edge in set(moving):
        for target, label in stationary:
            candidate = target - edge
            distance = abs(candidate - delta)
            stable = bool(held and held['time'] == target and held.get('moving_edge') == edge)
            if distance > threshold * (1.5 if stable else 1) or candidate < -minimum:
                continue
            if any(a+candidate < d and b+candidate > c
                   for selected, fixed in lanes for a, b in selected for c, d in fixed):
                continue
            choices.append((not stable, distance, target, edge, label, candidate))
    if not choices:
        return delta, None
    _, _, target, edge, label, delta = min(choices)
    return delta, dict(time=target, label=label, cue_id='', edge='', moving_edge=edge)
