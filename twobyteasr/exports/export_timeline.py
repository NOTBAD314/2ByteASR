"""Freeze the editor's timeline subtitle view at the export boundary."""
from copy import deepcopy
from pathlib import Path


def export_project_snapshot(project, *, start_ms=None, end_ms=None):
    from ..timeline.studio_edit_sequence import projected_cues
    snapshot = deepcopy(project)
    hidden = project.hidden_speaker_ids()
    visibility = project.studio_state.get('subtitle_track_visibility', {})
    snapshot.cues = deepcopy([c for c in projected_cues(project, domain="timeline")
                             if c.speaker_id not in hidden and visibility.get(c.speaker_id, True)
                             and (start_ms is None or c.end_ms > start_ms)
                             and (end_ms is None or c.start_ms < end_ms)])
    # Burn-in (libass, still frames, web renderer) shows the punctuation choice.
    from ..subtitle_rules.punctuation_style import mark_cues_styled, style_cues
    snapshot.cues = style_cues(project, snapshot.cues)
    mark_cues_styled(snapshot)  # compile_ass(snapshot) must not style them again (math formulas, ADR 0124)
    snapshot.render_settings['_cue_domain'] = 'timeline'
    # A live runtime has source cue lookups. It must never override the frozen
    # projected cues when building a visual snapshot in the export worker.
    snapshot.__dict__.pop('_studio_state_runtime', None)
    return snapshot


def write_export_ass(project, path, *, fps=None, skip_empty=False, start_ms=None, end_ms=None):
    snapshot = export_project_snapshot(project, start_ms=start_ms, end_ms=end_ms)
    if snapshot.cues or not skip_empty:
        from ..rendering.ass_compiler import compile_ass
        Path(path).write_text(compile_ass(snapshot, frame_rate=fps), encoding="utf-8-sig")
    return snapshot
