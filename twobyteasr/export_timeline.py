"""Freeze the editor's timeline subtitle view at the export boundary."""
from copy import deepcopy
from pathlib import Path


def export_project_snapshot(project):
    from .studio_edit_sequence import projected_cues
    snapshot = deepcopy(project)
    hidden = project.hidden_speaker_ids()
    snapshot.cues = deepcopy([c for c in projected_cues(project, domain="timeline")
                             if c.speaker_id not in hidden])
    # Burn-in (libass, still frames, web renderer) shows the punctuation choice.
    from .punctuation_style import style_cues
    snapshot.cues = style_cues(project, snapshot.cues)
    snapshot.render_settings['_cue_domain'] = 'timeline'
    # A live runtime has source cue lookups. It must never override the frozen
    # projected cues when building a visual snapshot in the export worker.
    snapshot.__dict__.pop('_studio_state_runtime', None)
    return snapshot


def write_export_ass(project, path, *, fps=None):
    from .ass_compiler import compile_ass
    snapshot = export_project_snapshot(project)
    Path(path).write_text(compile_ass(snapshot, frame_rate=fps), encoding="utf-8-sig")
    return snapshot
