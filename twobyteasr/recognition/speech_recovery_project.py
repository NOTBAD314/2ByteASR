"""Project-clock projection and undoable coverage updates for range recognition."""
from __future__ import annotations

import copy
import os

from .speech_coverage import KEY, pending, update_gap, classify_state


def audio_version(project, state):
    from ..subtitle_rules.current_issues import digest
    paths = sorted({os.path.normcase(s.source_path) for s in _input_segments(project, state)}
                   | {os.path.normcase(project.media.path)})
    files = []
    for path in paths:
        try:
            info = os.stat(path)
            files.append((path, info.st_size, info.st_mtime_ns))
        except OSError:
            files.append((path, None, None))
    return digest([state.get('identity'), files,
                   state.get('input_sequence'), state.get('input_offset_ms', 0)])


def _input_segments(project, state):
    from ..timeline.studio_edit_sequence import EditSequence, identity_segment
    snapshot = state.get('input_sequence')
    if snapshot:
        return EditSequence.from_dict(snapshot).segments
    return [identity_segment(project.media.path, round(state['duration']*1000))]


def _project_to_input(project, state, start, end):
    from ..timeline.studio_edit_sequence import sequence_of
    offset = state.get('input_offset_ms', 0)
    for current in sequence_of(project).segments:
        low, high = max(start, current.timeline_in_ms), min(end, current.timeline_out_ms)
        if high <= low or not current.duration_ms:
            continue
        rate = current.source_duration_ms/current.duration_ms
        a = current.source_in_ms+(low-current.timeline_in_ms)*rate
        b = current.source_in_ms+(high-current.timeline_in_ms)*rate
        for original in _input_segments(project, state):
            if os.path.normcase(original.source_path) != os.path.normcase(current.source_path):
                continue
            c, d = max(a, original.source_in_ms), min(b, original.source_out_ms)
            if d > c and original.source_duration_ms:
                scale = original.duration_ms/original.source_duration_ms
                yield ((original.timeline_in_ms+(c-original.source_in_ms)*scale-offset)/1000,
                       (original.timeline_in_ms+(d-original.source_in_ms)*scale-offset)/1000)


def project_ranges(project):
    from ..timeline.studio_edit_sequence import sequence_of
    if project is None:
        return []
    state = classify_state(project.generation_metadata.get(KEY))
    result = []
    offset = state.get('input_offset_ms', 0)
    version = audio_version(project, state) if state.get('gaps') else ''
    decisions = state.get('decisions') or {}
    for gap in pending(state):
        if any(d.get('status') == 'non_speech' and d.get('audio_version') == version
               and float(d.get('start', gap['start'])) <= gap['start']
               and float(d.get('end', gap['end'])) >= gap['end']
               for key, d in decisions.items() if key == gap['id'] or 'start' in d and 'end' in d):
            continue
        for low, high in gap.get('remaining_ranges', [[gap['start'], gap['end']]]):
            for original in _input_segments(project, state):
                a = max(round(low*1000)+offset, original.timeline_in_ms)
                b = min(round(high*1000)+offset, original.timeline_out_ms)
                if b <= a or not original.duration_ms:
                    continue
                rate = original.source_duration_ms/original.duration_ms
                source_start = original.source_in_ms+(a-original.timeline_in_ms)*rate
                source_end = original.source_in_ms+(b-original.timeline_in_ms)*rate
                for current in sequence_of(project).segments:
                    if os.path.normcase(current.source_path) != os.path.normcase(original.source_path):
                        continue
                    start, end = max(source_start, current.source_in_ms), min(source_end, current.source_out_ms)
                    if end <= start or not current.source_duration_ms:
                        continue
                    scale = current.duration_ms/current.source_duration_ms
                    result.append(dict(gap, timeline_start_ms=current.timeline_in_ms+round((start-current.source_in_ms)*scale),
                                       timeline_end_ms=current.timeline_in_ms+round((end-current.source_in_ms)*scale)))
    return result


def merge_project_range(project, plan):
    state = project.generation_metadata.get(KEY)
    if not state:
        return
    rows = []
    inserted = set(plan.inserted_ids)
    for cue in plan.cues:
        if cue.id in inserted:
            rows.extend(dict(start=a, end=b, text=cue.text)
                        for a,b in _project_to_input(project, state, cue.start_ms, cue.end_ms))
    for gap in pending(state):
        relevant = [row for row in rows if row['end'] > gap['start'] and row['start'] < gap['end']]
        if relevant:
            update_gap(gap, relevant, source='studio_range_recognition')
    project.generation_metadata[KEY] = copy.deepcopy(state)


def failed_range_attempt(project, bounds, error):
    state = project.generation_metadata.get(KEY)
    if not state or not bounds:
        return False
    spans = list(_project_to_input(project, state, *bounds))
    changed = False
    for gap in pending(state):
        if any(min(b, gap['end']) > max(a, gap['start']) for a,b in spans):
            update_gap(gap, [], source='studio_range_recognition',
                       error='' if error == 'no_usable_captions' else error)
            changed = True
    return changed


def validate_range_backend(snapshot, backend):
    """A known safety refusal cannot re-enter a remote service as a crop."""
    bounds = (snapshot or {}).get('range_ms')
    data = (snapshot or {}).get('project') or {}
    state = (data.get('generation_metadata') or {}).get(KEY) or {}
    refused = [gap for gap in state.get('gaps', []) if gap.get('reason') == 'content_blocked']
    if backend != 'api' or not bounds or not refused:
        return
    from ..projects.studio_project import SubtitleProject
    from ..providers.qwen31_asr import ASRProtocolError
    project = SubtitleProject.from_dict(copy.deepcopy(data))
    state = copy.deepcopy(state)
    state['gaps'] = [dict(gap, status='pending', remaining_ranges=[[gap['start'], gap['end']]]) for gap in refused]
    project.generation_metadata[KEY] = state
    if any(row['timeline_end_ms'] > bounds[0] and row['timeline_start_ms'] < bounds[1]
           for row in project_ranges(project)):
        raise ASRProtocolError('此范围已有服务内容安全拒绝，请选择本地模型恢复。', 'content_blocked')
