"""Freeze the editor's timeline subtitle view at the export boundary."""
from copy import deepcopy
from pathlib import Path


def output_canvas(snapshot, width=None, height=None):
    """Adapt a worker-owned project to the requested output aspect ratio.

    Equal ratios retain the authored design canvas exactly. A new ratio keeps
    its design height/font sizes and changes the available width; explicit
    horizontal anchors retain their fraction of the canvas. Source/video
    transforms are normalized and keep their existing contain/cover/stretch
    policy. This never changes the canonical editor project.
    """
    old_width = max(1, int(snapshot.render_settings.get('play_res_x', 1920)))
    old_height = max(1, int(snapshot.render_settings.get('play_res_y', 1080)))
    width = max(1, int(width or snapshot.media.width or old_width))
    height = max(1, int(height or snapshot.media.height or old_height))
    same_ratio = abs(width*old_height-height*old_width) <= max(width, height)
    new_width = old_width if same_ratio else max(1, round(old_height*width/height))
    ratio = new_width/old_width
    if not same_ratio:
        for style in snapshot.styles:
            if style.position_x is not None:
                style.position_x *= ratio
        def transform(value):
            if not isinstance(value, dict):
                return
            for key in ('position_x', '_name_layout_width'):
                if isinstance(value.get(key), (int, float)):
                    value[key] *= ratio
            for key in ('language_layers', '_geometry_base', 'initial_layout'):
                nested = value.get(key)
                if key == 'language_layers' and isinstance(nested, dict):
                    for layer in nested.values():
                        transform(layer)
                else:
                    transform(nested)
        for cue in snapshot.cues:
            transform(cue.transform)
        for recipe in snapshot.style_recipes.values():
            layout = recipe.get('layout', {}) if isinstance(recipe, dict) else {}
            if isinstance(layout.get('positionX'), (int, float)):
                layout['positionX'] *= ratio
        for cue in snapshot.cues:
            for key in ('_recipe_base', '_recipe_patch'):
                recipe = cue.appearance_override.get(key)
                layout = recipe.get('layout', {}) if isinstance(recipe, dict) else {}
                if isinstance(layout.get('positionX'), (int, float)):
                    layout['positionX'] *= ratio
        group = snapshot.studio_state.get('caption_group_transform')
        if isinstance(group, dict) and isinstance(group.get('dx'), (int, float)):
            group['dx'] *= ratio
        snapshot.render_settings.update(play_res_x=new_width, play_res_y=old_height)
    snapshot.__dict__['_output_canvas'] = dict(
        authored=[old_width, old_height], design=[new_width, old_height], output=[width, height],
        relayout=not same_ratio, rule='preserve-design-height', video_fit='per-clip')
    return snapshot


def export_project_snapshot(project, *, start_ms=None, end_ms=None, width=None, height=None):
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
    return output_canvas(snapshot, width, height) if width is not None or height is not None else snapshot


def write_export_ass(project, path, *, fps=None, skip_empty=False, start_ms=None, end_ms=None,
                     width=None, height=None, require_layout_fit=False):
    snapshot = export_project_snapshot(project, start_ms=start_ms, end_ms=end_ms, width=width, height=height)
    if require_layout_fit:
        from .output_caption_layout import require_layout_fit as validate_layout
        validate_layout(snapshot)
    if snapshot.cues or not skip_empty:
        from ..rendering.ass_compiler import compile_ass
        Path(path).write_text(compile_ass(snapshot, frame_rate=fps), encoding="utf-8-sig")
    return snapshot
