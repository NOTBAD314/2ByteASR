"""One-time initial overlap layout, persisted alongside each cue's transform.

Allocation is a generation/explicit edit operation. Playback and exports read
the saved anchors through style_resolution, and never redo collision layout.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from copy import deepcopy
from collections.abc import Mapping

_VISIBLE_GAP_AT_1080 = 16.0


def _transform(cue):
    value = getattr(cue, 'transform', {})
    if isinstance(value, Mapping):
        return dict(value)
    from .studio_revisions import thaw_json
    return thaw_json(value) or {}


def manual_position(cue):
    value = _transform(cue)
    return bool(value.get('position_locked') or any(
        key in value for key in ('position_x', 'position_y', 'web_placement')))


@dataclass(frozen=True, slots=True)
class StackLayout:
    """Resolved upward offsets in play-resolution pixels, keyed by cue id."""

    offsets: dict[str, float]
    warnings: tuple[str, ...] = ()

    def offset_for(self, cue_id: str) -> float:
        return self.offsets.get(str(cue_id), 0.0)

    @property
    def signature(self) -> str:
        if not self.offsets:
            return ""
        items = sorted(self.offsets.items())
        return ";".join(f"{key}:{value:.1f}" for key, value in items)


def _cluster_overlaps(cues: Sequence) -> list[list]:
    """Group cues into connected overlap clusters (transitive closure).

    Input order is irrelevant; each cluster is returned sorted by
    (start_ms, end_ms, id) — the same ordering cue runtime state uses, so the
    layout is stable across seeks and replays.
    """
    ordered = sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    clusters: list[list] = []
    current: list = []
    cluster_end = -1
    for cue in ordered:
        if current and cue.start_ms >= cluster_end:
            clusters.append(current)
            current = []
            cluster_end = -1
        current.append(cue)
        cluster_end = max(cluster_end, cue.end_ms)
    if current:
        clusters.append(current)
    return [cluster for cluster in clusters if len(cluster) > 1]


def _pair_overlap_ms(a, b) -> float:
    return max(0.0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))


def _cue_stack_metrics(resolved) -> tuple[float, float]:
    """Visible ink height plus stroke outsets, never the selection box."""
    style = resolved.style
    layout = dict(resolved.recipe.layout or {})
    line_count = max(1, int(resolved.line_count or layout.get("lineCount") or 1))
    line_height = float(layout.get("lineHeightPx") or 0.0)
    if line_height <= 0.0:
        line_height = float(style.font_size) * 1.16
    scale_y = max(0.05, float(style.scale_y or 100.0) / 100.0)
    slab = max(float(style.outline_width or 0.0), float(getattr(style, "outline2_width", 0.0) or 0.0))
    slab = max(slab, float(style.shadow or 0.0))
    ink_width = float(getattr(resolved, 'measured_width', 0) or 0)
    ink_height = line_count * line_height
    if getattr(resolved, 'text', None) is not None:
        from .resolved_caption_style import visible_glyph_size
        ink_width, ink_height = visible_glyph_size(resolved.text, style.font_family,
            style.bold, style.font_size, style.spacing, style.font_weight,
            style.font_style_name, style.font_file, style.font_face_index)
    return ink_height * scale_y + slab * 2, ink_width * float(getattr(style, 'scale_x', 100))/100


def compute_stack_layout(cues, *, resolve_one, play_res_y, enabled=True, play_res_x=1920, effect_for=None, bounds_for=None,
                         extra_height=None):
    """Allocate stable spatial positions for each full cue lifetime.

    Only temporally overlapping rectangles reserve space. A cue keeps its
    allocated position after peers finish; a later cue takes the lowest row
    that is free for its whole lifetime.
    Fixed authored positions are obstacles, never moved by this operation.
    """
    if not enabled:return StackLayout({})
    offsets, warnings = {}, []
    for cluster in _cluster_overlaps(list(cues)):
        placed=[]
        measured_rows=[]
        fixed = manual_position
        # Identity and track order never constrain vertical order. Existing
        # fixed positions are obstacles only for an explicit allocation.
        ordered=sorted(cluster,key=lambda c:(not fixed(c),c.start_ms,c.end_ms,c.id))
        for cue in ordered:
            try:
                resolved=resolve_one(cue)
                if resolved is None:continue
                style=resolved.style
                height,ink_width=_cue_stack_metrics(resolved)
                # A bilingual group (translation line) reserves its whole height.
                if extra_height is not None:height+=float(extra_height(cue) or 0.)
                gap=max(4.,_VISIBLE_GAP_AT_1080*float(play_res_y)/1080)
                recipe=resolved.recipe
                shadow=(getattr(recipe,'outline',{}) or {}).get('shadow',{}) or {}
                # Reading separation follows solid ink/strokes. Reserving the
                # entire faint blur halo on both sides creates a conspicuous
                # empty band; the style's shadow outset is already included.
                extra=max(0., abs(float(shadow.get('offsetY',shadow.get('offset_y',0)) or 0))
                          - float(getattr(style,'shadow',0) or 0)) if shadow.get('enabled',True) else 0.
                height+=extra
                background=getattr(recipe,'background',{}) or {}
                if isinstance(background,dict) and background.get('enabled'):
                    height+=float(background.get('paddingY',background.get('padding',0)) or 0)*2
                width=min(float(play_res_x),ink_width or float(play_res_x)*.8)
                # Reserve the entire supported entry/exit motion envelope;
                # layout never changes while an animation is playing.
                motion=getattr(recipe,'motion',{}) or {}
                motion_effect=effect_for(cue) if effect_for else {k:motion.get(k,{}) for k in ('entry','exit')}
                from .effect_dsl import validate_effect,STRENGTH_PRESETS
                movement=validate_effect(motion_effect)
                sx=sy=0.;peak=1.
                for part in ('entry','exit'):
                    spec=movement.get(part,{})
                    factor=STRENGTH_PRESETS.get(spec.get('strength','medium'),1.)
                    sx=max(sx,abs(float(spec.get('offset_x',0)))*factor)
                    sy=max(sy,abs(float(spec.get('offset_y',0)))*factor)
                    peak=max(peak,*[1+(float(spec.get(k,100))/100-1)*factor for k in ('scale_from','scale_to','overshoot')])
                height=height*peak+2*sy;width=width*peak+2*sx
                x=getattr(style,'position_x',None)
                x=float(x if x is not None else play_res_x/2)
                y=getattr(style,'position_y',None)
                y=float(y if y is not None else play_res_y-getattr(style,'margin_v',40))
                alignment=int(getattr(style,'alignment',2))
                ax=(0,.5,1)[(alignment-1)%3];ay=(1,.5,0)[(alignment-1)//3]
                x+=sx*(2*ax-1);y+=sy*(2*ay-1)
                left,right=x-width*ax,x+width*(1-ax)
                top,bottom=y-height*ay,y+height*(1-ay)
                if getattr(recipe, 'web_theme', {}):
                    measured = bounds_for(cue, resolved) if bounds_for else None
                    if measured is None:
                        warnings.append(f'{cue.id}:HTML装饰未测量，当前仅按文字避让；右键“字幕自动避让”可测量，或手动固定位置')
                    else:
                        left, top, width, height = measured
                        right, bottom = left+width, top+height
                measured_rows.append((cue,left,top,right,bottom,height,gap))
            except Exception as exc:
                warnings.append(f'{cue.id}:无法测量字幕布局: {type(exc).__name__}')
        for cue,left,original_top,right,original_bottom,height,gap in measured_rows:
            top,bottom=original_top,original_bottom
            obstacles=[r for other,r in placed if _pair_overlap_ms(cue,other)>0]
            def collision(rect, room=gap):
                return left<rect[2] and right>rect[0] and top<rect[3]+room and bottom>rect[1]-room
            if not fixed(cue):
                # The lowest row free for this cue's whole lifetime (2026-10-10,
                # user): in A -> A+B -> B+C, C takes the row A left instead of
                # climbing above B, so a long exchange stays two rows high.
                # Each cue keeps this one anchor for its whole lifetime.
                # A row left by a slightly shorter caption still fits when at
                # least half the spacing remains: glyph heights differ by
                # fractions of a pixel (61.6 vs 62.7), which must not cost a row.
                top, bottom = original_top, original_bottom
                for candidate in sorted({0., *(max(0., original_bottom-r[1]+gap) for r in obstacles)}):
                    top, bottom = original_top-candidate, original_bottom-candidate
                    if not any(collision(r, gap*.5) for r in obstacles):
                        break
                else:
                    top, bottom = original_top, original_bottom
                # Explicit positions may use different baselines. Clear their
                # actual ink edge, without another full (possibly tall) band.
                if any(collision(r, gap*.5) for r in obstacles):
                    for _ in range(len(obstacles)+1):
                        hits = [rect for rect in obstacles if collision(rect)]
                        if not hits:break
                        shift = max(bottom - rect[1] + gap for rect in hits)
                        top -= shift; bottom -= shift
                if top<play_res_y*.03:
                    warnings.append(f'{cue.id}:画面高度不足，请调整字号或固定位置')
                    # A very long unbroken handoff chain cannot satisfy both
                    # fixed lifetime anchors and endless upward ordering. Use
                    # the lowest free location with a warning, never climb
                    # offscreen or move previously placed captions.
                    top,bottom=original_top,original_bottom
                    for candidate in sorted({0.,*(max(0.,original_bottom-r[1]+gap) for r in obstacles)}):
                        top,bottom=original_top-candidate,original_bottom-candidate
                        if top>=play_res_y*.03 and not any(collision(r) for r in obstacles):break
                    else:top,bottom=original_top,original_bottom
            elif any(collision(rect) for rect in obstacles):
                warnings.append(f'{cue.id}:固定位置发生遮挡，请移动字幕或解除固定')
            offset=original_bottom-bottom
            if abs(offset)>.5:offsets[str(cue.id)]=round(offset,1)
            placed.append((cue,(left,top,right,bottom)))
    return StackLayout(offsets,tuple(warnings))


def _bilingual_extra(project, cue, width):
    from .bilingual_layout import group_extra_for
    from .studio_edit_sequence import source_cue_id_of
    source = next((c for c in project.cues if c.id in (cue.id, source_cue_id_of(cue.id))), None)
    return group_extra_for(project, source, width) if source is not None else 0.


def project_stack_layout(project):
    """Compatibility diagnostics only; saved anchors require no extra offset."""
    receipt = project.studio_state.get('initial_subtitle_layout', {})
    return StackLayout({}, tuple(receipt.get('warnings', ())) if isinstance(receipt, dict) else ())


def initialize_project_layout(project, *, cue_ids=None, replace=False):
    """Persist layout only for newly generated cues or an explicit edit scope.

    A normal open/render never calls this. ``replace`` is reserved for the
    user's explicit re-layout command; it may reset selected manual positions.
    Unselected and already arranged captions become immovable obstacles.
    """
    from .resolved_caption_style import resolve_caption_style
    from .visual_snapshot import _anchor
    from .theme_visual_bounds import measured_bounds
    from .studio_edit_sequence import projected_cues, source_cue_id_of
    selected = set(cue_ids) if cue_ids is not None else {c.id for c in project.cues}
    targets = {c.id for c in project.cues if c.id in selected and
        (replace or (not manual_position(c) and not _transform(c).get('initial_layout')))}
    if not targets:
        return StackLayout({})
    width = int(project.render_settings.get('play_res_x', 1920))
    height = int(project.render_settings.get('play_res_y', 1080))
    local = deepcopy(project)
    for c in local.cues:
        transform = _transform(c)
        if c.id in targets:
            transform.pop('initial_layout', None)
            if replace:
                for key in ('position_x', 'position_y', 'position_locked', 'web_placement'):
                    transform.pop(key, None)
            c.transform = transform
        else:
            transform['position_locked'] = True
            c.transform = transform
    rendered = list(projected_cues(local))
    resolved = {}
    for c in rendered:
        item = resolve_caption_style(local.styles, local.speakers, c, local.style_recipes, width)
        resolved[c.id] = item
    layout = compute_stack_layout(rendered, resolve_one=lambda c: resolved[c.id],
        play_res_y=height, play_res_x=width,
        enabled=project.studio_state.get('auto_subtitle_stacking', True),
        effect_for=lambda c: project.effects.get(c.effect_id, {}),
        bounds_for=lambda c,r: measured_bounds(local,c,r,width,height),
        extra_height=lambda c: _bilingual_extra(local, c, width))
    positions = {}
    for c in rendered:
        source_id = c.id if c.id in targets else source_cue_id_of(c.id)
        if source_id not in targets:
            continue
        x, y, _, _ = _anchor(resolved[c.id].style, width, height)
        value = dict(version=1, source='temporal_overlap',
            position_x=round(x, 3), position_y=round(y-layout.offset_for(c.id), 3),
            offset_y=layout.offset_for(c.id), play_res_x=width, play_res_y=height)
        # Repeated source instances retain one stable anchor, choosing the
        # upper allocation needed by the most constrained visible instance.
        if source_id not in positions or value['position_y'] < positions[source_id]['position_y']:
            positions[source_id] = value
    for c in project.cues:
        if c.id in positions:
            transform = _transform(c)
            if replace:
                for key in ('position_x', 'position_y', 'position_locked', 'web_placement'):
                    transform.pop(key, None)
            transform['initial_layout'] = positions[c.id]
            c.transform = transform
    project.studio_state['initial_subtitle_layout'] = dict(version=1, warnings=list(layout.warnings),
        initialized_cue_ids=sorted(positions))
    return layout


def rearrange_subtitles_command(project, cue_ids, changed=None):
    """Explicit scoped re-layout as one existing presentation undo command."""
    from .studio_commands import SetCuesPresentationCommand
    from .studio_edit_sequence import source_cue_id_of
    known = {c.id for c in project.cues}
    selected = {str(key) if str(key) in known else source_cue_id_of(str(key)) for key in cue_ids}
    selected &= known
    if not selected:
        return None, StackLayout({})
    local = deepcopy(project)
    layout = initialize_project_layout(local, cue_ids=selected, replace=True)
    targets = {c.id: c for c in local.cues if c.id in selected}
    command = SetCuesPresentationCommand(project, selected, style_id='default', effect_id='none',
        style_ids={key: c.style_id for key,c in targets.items()},
        effect_ids={key: c.effect_id for key,c in targets.items()},
        transform_overrides={key: deepcopy(c.transform) for key,c in targets.items()},
        text=f'重新排版 {len(selected)} 条字幕', merge_enabled=False, changed=changed)
    if command.before == command.after:
        return None, layout
    return command, layout


def stack_batch_presentation(command):
    """Keep a geometry/preset batch and its automatic layout in one undo step.

    Call only from explicit batch-style actions that apply geometry. Pointer
    drags, single-cue edits and batches that preserve positions never enter.
    """
    if len(command.after) < 2 or not command.project.studio_state.get('auto_subtitle_stacking', True):
        return command
    local = deepcopy(command.project)
    local.styles = deepcopy(command.after_styles)
    local.effects = deepcopy(command.after_effects)
    local.style_recipes = deepcopy(command.after_style_recipes)
    targets = []
    for cue in local.cues:
        if cue.id not in command.after:
            continue
        cue.style_id, cue.effect_id, cue.base_preset_id, cue.appearance_override, cue.transform = deepcopy(command.after[cue.id])
        from .subtitle_layout_ui import _has_keyframes
        if not cue.transform.get('position_locked') and not _has_keyframes(cue.transform):
            targets.append(cue.id)
    layout = initialize_project_layout(local, cue_ids=targets, replace=True)
    for cue in local.cues:
        if cue.id in targets:
            command.after[cue.id] = (*command.after[cue.id][:4], deepcopy(cue.transform))
    command.layout_warnings = layout.warnings
    return command
