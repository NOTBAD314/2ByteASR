"""Revision-owned playback indexes. No Qt, transport, workers, or editable state.

The canonical project/runtime owns this derived plan. Edits (including undo)
invalidate it before notifying views. Sampling only visits active intervals;
time mapping and transition envelopes remain continuous, not frame-quantized.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import copy
from time import perf_counter


class IntervalIndex:
    """Half-open intervals with stable input order, including overlaps."""
    def __init__(self, rows, start, end):
        ordered = sorted(enumerate(rows), key=lambda pair: (start(pair[1]), pair[0]))
        self.rows = tuple((order, row, int(end(row))) for order, row in ordered)
        self.starts = tuple(int(start(row)) for _, row in ordered)
        maximum = 0
        prefix = []
        for _, _, finish in self.rows:
            maximum = max(maximum, finish)
            prefix.append(maximum)
        self.prefix_ends = tuple(prefix)

    def at(self, milliseconds):
        index = bisect_right(self.starts, milliseconds) - 1
        found = []
        while index >= 0 and self.prefix_ends[index] > milliseconds:
            order, row, end = self.rows[index]
            if end > milliseconds:
                found.append((order, row))
            index -= 1
        return tuple(row for _, row in sorted(found))


class PlaybackPlan:
    def __init__(self, project, revision):
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        from ..timeline.studio_media_pool import primary_video_track_id, media_graph_duration_ms
        from ..timeline.studio_transitions import transition_records, transition_windows
        from .audio_graph import capture_audio_graph

        began = perf_counter()
        self.revision = revision
        self.project_identity = id(project)
        self.assets = {asset.asset_id: asset for asset in project.media_pool}
        self.primary_track_id = primary_video_track_id(project)
        self.duration_ms = timeline_duration_ms(project)
        self.graph_duration_ms = media_graph_duration_ms(project)
        self.windows = transition_windows(project, 'video')
        transitions = transition_records(project, 'video')
        self.tracks = []
        upcoming = []
        for track in sorted(project.video_tracks, key=lambda item: item.z_index):
            if not track.enabled:
                continue
            clips = []
            for original in track.clips:
                asset = self.assets.get(original.asset_id)
                if not original.enabled or asset is None or asset.offline:
                    continue
                window = self.windows.get((track.id, original.id), self.windows.get(original.id))
                clip = original
                if window:
                    clip = copy.copy(original)
                    for name in ('source_in_ms', 'source_out_ms', 'timeline_in_ms', 'timeline_out_ms'):
                        setattr(clip, name, window[name])
                clips.append(clip)
                if track.id != self.primary_track_id:
                    upcoming.append((original.timeline_in_ms, track, original, asset))
            index = IntervalIndex(clips, lambda x: x.timeline_in_ms, lambda x: x.timeline_out_ms)
            seams = IntervalIndex([x for x in transitions if x.get('track_id') == track.id and x.get('edge') == 'seam'],
                                  lambda x: x['start_ms'], lambda x: x['end_ms'])
            self.tracks.append((track, index, seams))
        self.upcoming = tuple(sorted(upcoming, key=lambda x: x[0]))
        self.upcoming_starts = tuple(row[0] for row in self.upcoming)
        self.audio_graph = capture_audio_graph(project)
        self.audio_index = IntervalIndex(self.audio_graph['segments'],
                                        lambda x: x['timeline_in_ms'], lambda x: x['timeline_out_ms'])
        self.build_ms = (perf_counter() - began) * 1000
        self.samples = 0

    def video_at(self, milliseconds):
        self.samples += 1
        matches = []
        for track, clips, seams in self.tracks:
            active = clips.at(milliseconds)
            seam_ids = {key for seam in seams.at(milliseconds)
                        for key in (seam['left_clip_id'], seam['right_clip_id'])}
            seam_clips = [clip for clip in active if clip.id in seam_ids]
            matches.extend((track, clip) for clip in (seam_clips or active[-1:]))
        return matches

    def audio_at(self, milliseconds):
        return [{**row, 'project_ms': int(milliseconds),
                 'source_ms': row['source_in_ms'] + round((milliseconds-row['timeline_in_ms'])*row['playback_rate'])}
                for row in self.audio_index.at(milliseconds)]

    def prewarm_at(self, milliseconds, horizon_ms=1500):
        first = bisect_right(self.upcoming_starts, milliseconds)
        last = bisect_right(self.upcoming_starts, milliseconds + horizon_ms)
        return self.upcoming[first:last]


def playback_plan(project):
    """O(1) revision check. Never hash or deep-compare the project on a tick."""
    from ..projects.studio_runtime_state import state_for
    runtime = state_for(project)
    plan = getattr(runtime, '_playback_plan', None)
    revision = getattr(runtime, 'playback_revision', 0)
    if plan is None or plan.revision != revision or plan.project_identity != id(project):
        plan = runtime._playback_plan = PlaybackPlan(project, revision)
        runtime.playback_plan_builds = getattr(runtime, 'playback_plan_builds', 0) + 1
    return plan


def invalidate_playback_plan(project, reason):
    from ..projects.studio_runtime_state import state_for
    runtime = state_for(project)
    runtime.playback_revision = getattr(runtime, 'playback_revision', 0) + 1
    runtime.playback_invalidation = str(reason)
    runtime._playback_plan = None
