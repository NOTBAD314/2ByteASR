"""Read-only instance layouts in video play-resolution units.

Snapshots contain authored baselines. A Layout contains only temporary vertical
offsets; neither solving nor rendering modifies a cue, recipe or undo stack.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from threading import RLock

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QGuiApplication, QTransform


@dataclass(frozen=True)
class CollisionLayout:
    offsets: dict[str, float]
    warnings: tuple[str, ...] = ()


_bounds_cache = OrderedDict()
_bounds_lock = RLock()


def visual_bounds(snapshot):
    """Unclipped visual envelope, measured once per content/style/transform.

    Uses the renderer's glyph path, not a selected frame or control handles.
    Blur masks reserve visible ink, excluding transparent allocation padding.
    """
    key = (snapshot.pixel_hash(resolution=(snapshot.playres_x, snapshot.playres_y)),
           snapshot.motion_hash(), snapshot.end_ms-snapshot.start_ms)
    with _bounds_lock:
        if key in _bounds_cache:
            _bounds_cache.move_to_end(key)
            return QRectF(_bounds_cache[key])
    from ..rendering.advanced_live_renderer import caption_ink_layout, _expanded_bounds
    if QGuiApplication.instance() is not None:
        ink = caption_ink_layout(snapshot)[6]
    else:
        # Headless ASS/text consumers must not construct a QFont without Qt.
        from .resolved_caption_style import visible_glyph_size
        style = snapshot.resolved_caption.style
        w, h = visible_glyph_size(snapshot.text, style.font_family, style.bold,
            style.font_size, style.spacing, style.font_weight, style.font_style_name,
            style.font_file, style.font_face_index)
        ink = QRectF(-w*snapshot.anchor_x, -h*snapshot.anchor_y, w, h)
    stroke = 0.
    for layer in snapshot.strokes:
        width = float(layer.get('width', 0) or 0)
        alignment = layer.get('alignment', 'OUTSIDE')
        if alignment == 'CENTER':
            width *= .5
        elif alignment == 'INSIDE':
            width = 0.
        stroke = max(stroke, width)
    rect = ink.adjusted(-stroke, -stroke, stroke, stroke)
    shadow = snapshot.shadow
    if shadow.get('enabled'):
        spread = max(0., float(shadow.get('spread', 0) or 0))
        radius = max(0., float(shadow.get('blur_radius', shadow.get('blur', 0)) or 0))
        from statistics import NormalDist
        opacity = float(shadow.get('opacity', min(.78, float(shadow.get('strength', 1))* .24)))
        color = QColor(shadow.get('color') or '#FF000000')
        opacity *= color.alphaF() if color.isValid() else 1.
        # Gaussian edge at 8/255 alpha. The 3*sigma raster allocation is
        # transparent storage, not the shadow's visible collision boundary.
        fraction = min(.49, 8 / max(8.01, 255 * opacity))
        pad = spread + radius * max(0., NormalDist().inv_cdf(1-fraction))
        if opacity >= 8/255:
            rect = rect.united(ink.adjusted(-pad, -pad, pad, pad).translated(
                float(shadow.get('offset_x', shadow.get('offsetX', 0)) or 0),
                float(shadow.get('offset_y', shadow.get('offsetY', 0)) or 0)))
    glow = snapshot.glow
    if glow.get('enabled') and float(glow.get('opacity', .45)) > 0:
        pad = max(0., float(glow.get('spread', 0) or 0)) + max(
            .6, float(glow.get('radius', glow.get('blur', 4)) or 0)*2.2)
        rect = rect.united(ink.adjusted(-pad, -pad, pad, pad))
    recipe = snapshot.style_recipe
    background = recipe.get('background') or {}
    if background.get('enabled') and float(background.get('opacity', 1)) > 0:
        from .style_recipe import background_padding
        top, right, bottom, left = background_padding(background)
        rect = rect.united(ink.adjusted(-left, -top, right, bottom))
    graph = recipe.get('visualGraph') or {}
    # Panels and cue-space decorations use the same bounded expansion contract
    # as LIVE; ambient/video-canvas layers do not occupy a subtitle row.
    for layer in [graph.get('panelLayer') or {}, *(graph.get('decorationLayers') or [])]:
        if layer.get('primitive', 'NONE') == 'NONE' or layer.get('coordinateSpace') == 'video_canvas':
            continue
        params = layer.get('params') or {}
        expanded = _expanded_bounds(ink, params, 1.)
        pad = float(params.get('outlineWidth', params.get('borderWidth', 2)) or 0)
        rect = rect.united(expanded.adjusted(-pad, -pad, pad, pad))
    transform = QTransform()
    transform.translate(snapshot.position_x, snapshot.position_y)
    transform.rotate(snapshot.rotation)
    transform.scale(snapshot.scale_x, snapshot.scale_y)
    rect = transform.mapRect(rect)
    # Keep a stable envelope through entry/exit motion. Sampling keyframes is
    # geometry only, and is cached along with the static visual bounds.
    from ..rendering.studio_live_canvas import compiled_scene_for_snapshot
    scene = compiled_scene_for_snapshot(snapshot)
    if scene and scene.tracks:
        times = {0, snapshot.end_ms-snapshot.start_ms}
        for _, _, keyframes, _ in scene.tracks:
            times.update(k.time_ms for k in keyframes)
        original = QRectF(rect)
        for at in times:
            values = scene.sample(at).values
            group = values.get('group', {})
            for layer in [group, *[v for k, v in values.items() if k != 'group']]:
                sx = float(layer.get('scale_x', layer.get('scale', 1)) or 1)
                sy = float(layer.get('scale_y', layer.get('scale', 1)) or 1)
                if layer is not group:
                    sx *= float(group.get('scale_x', group.get('scale', 1)) or 1)
                    sy *= float(group.get('scale_y', group.get('scale', 1)) or 1)
                motion = QTransform()
                motion.translate(snapshot.position_x+float(layer.get('x', 0) or 0)+(float(group.get('x', 0) or 0) if layer is not group else 0),
                                 snapshot.position_y+float(layer.get('y', 0) or 0)+(float(group.get('y', 0) or 0) if layer is not group else 0))
                motion.rotate(float(layer.get('rotation', 0) or 0)+(float(group.get('rotation', 0) or 0) if layer is not group else 0))
                motion.scale(sx, sy)
                motion.translate(-snapshot.position_x, -snapshot.position_y)
                rect = rect.united(motion.mapRect(original))
    # One logical pixel for antialiasing and fractional raster rounding.
    rect.adjust(-1, -1, 1, 1)
    with _bounds_lock:
        _bounds_cache[key] = QRectF(rect)
        while len(_bounds_cache) > 4096:
            _bounds_cache.popitem(last=False)
    return rect


def solve_layout(snapshots, *, enabled=True, bounds_for=None, fixed_offsets=None):
    """Place newcomers around fixed live instances in video coordinates."""
    if not enabled:
        return CollisionLayout({})
    snapshots = tuple(snapshots)
    if not snapshots:
        return CollisionLayout({})
    if len(snapshots) == 1:
        return CollisionLayout({snapshots[0].cue_id: 0.})
    gap = 8.*snapshots[0].playres_y/1080.
    # Translation companions move with their original, never against it.
    from .bilingual_layout import is_companion
    groups, warnings = {}, []
    for snapshot in snapshots:
        group = snapshot.cue_id[:-3] if is_companion(snapshot.cue_id) else snapshot.cue_id
        recipe = snapshot.style_recipe
        panel = (recipe.get('visualGraph') or {}).get('panelLayer') or {}
        if (not snapshot.text.strip() and not recipe.get('webTheme')
                and not (recipe.get('background') or {}).get('enabled')
                and panel.get('primitive', 'NONE') == 'NONE'):
            continue
        box = (bounds_for(snapshot) if bounds_for else None) or getattr(snapshot, 'collision_bounds', None)
        if box is None:
            if snapshot.style_recipe.get('webTheme'):
                warnings.append(f'{snapshot.cue_id}:HTML装饰尚未测量，暂按文字边界避让；请先测量主题边界')
            try:
                box = visual_bounds(snapshot)
            except Exception as exc:
                # A malformed sibling still follows the renderer's per-cue
                # fallback contract; it cannot abort the healthy scene.
                warnings.append(f'{snapshot.cue_id}:字幕边界度量失败({type(exc).__name__})，暂按保守文字框避让')
                width = min(snapshot.playres_x, max(1,len(snapshot.text))*snapshot.font_size)
                height = snapshot.font_size*max(1,len(snapshot.text.splitlines()))*1.5
                box = QRectF(snapshot.position_x-width*snapshot.anchor_x,
                    snapshot.position_y-height*snapshot.anchor_y,width,height)
        if not isinstance(box, QRectF):
            box = QRectF(*box)
        row = groups.setdefault(group, [snapshot, QRectF(box), []])
        row[1] = row[1].united(box)
        row[2].append(snapshot.cue_id)
    placed, offsets = [], {}
    fixed_offsets = fixed_offsets or {}
    for snapshot, original, ids in groups.values():
        if any(key in fixed_offsets for key in ids):
            offset = next(fixed_offsets[key] for key in ids if key in fixed_offsets)
            placed.append(original.translated(0, -offset))
            offsets.update((key, offset) for key in ids)
    for snapshot, original, ids in groups.values():
        if getattr(snapshot, 'position_locked', False) and not any(key in offsets for key in ids):
            if any(original.intersects(box) for box in placed):
                warnings.append(f'{snapshot.cue_id}:人工锁定位置与显示中的字幕相交，请手动调整')
            placed.append(original)
            offsets.update((key, 0.) for key in ids)
    for _, (snapshot, original, ids) in sorted(groups.items(),
            key=lambda pair: (pair[1][0].start_ms, pair[1][0].end_ms, pair[0])):
        if any(key in offsets for key in ids):
            continue
        obstacles = [r for r in placed if original.left() < r.right() and original.right() > r.left()]
        candidates = {0.}
        for rect in obstacles:
            candidates.add(original.bottom()-rect.top()+gap)
            candidates.add(original.top()-rect.bottom()-gap)
        box = None
        # The nearest legal edge is optimal in one vertical dimension.
        # Prefer upward movement on equal distances, and support top anchors.
        for offset in sorted(candidates, key=lambda value: (abs(value), value < 0)):
            candidate = original.translated(0, -offset)
            if (candidate.top() >= 0 and candidate.bottom() <= snapshot.playres_y
                    and not any(candidate.top() < rect.bottom()+gap
                                and candidate.bottom() > rect.top()-gap for rect in obstacles)):
                box = candidate
                break
        if box is None:
            warnings.append(f'{snapshot.cue_id}:画面高度不足，保留基准位置；请手动调整字幕布局')
            box = original
        offset = original.top()-box.top()
        offsets.update((key, offset) for key in ids)
        placed.append(box)
    return CollisionLayout(offsets, tuple(warnings))


def shifted_snapshot(snapshot, offset):
    """An export-local view; baseline snapshot and authored recipe stay intact."""
    if not offset:
        return snapshot
    import copy
    recipe = copy.deepcopy(snapshot.style_recipe)
    recipe.setdefault('layout', {})['positionY'] = snapshot.position_y-offset
    placement = recipe['layout'].get('webPlacement')
    if placement:
        placement['y'] = float(placement.get('y', .5))-offset/snapshot.playres_y
    return replace(snapshot, position_y=snapshot.position_y-offset, style_recipe=recipe)


def layout_schedule(snapshots, *, enabled=True, bounds_for=None):
    """Assign one position per instance using half-open start/end events.

    End events release slots. Only starting captions are placed, so a survivor
    never moves when a peer ends. Seeking and export replay the same plan.
    """
    snapshots = tuple(snapshots)
    layout = instance_layout(snapshots, enabled=enabled, bounds_for=bounds_for)
    return {s.cue_id: [(s.start_ms, s.end_ms, layout.offsets.get(s.cue_id, 0.))]
            for s in snapshots}


def instance_layout(snapshots, *, enabled=True, bounds_for=None):
    snapshots = tuple(snapshots)
    offsets, warnings = {}, []
    events = {}
    for s in snapshots:
        events.setdefault(s.start_ms, [[], []])[1].append(s)
        events.setdefault(s.end_ms, [[], []])[0].append(s)
    active = {}
    for at in sorted(events):
        ending, starting = events[at]
        for s in ending:
            active.pop(s.cue_id, None)
        if starting:
            layout = solve_layout([*active.values(), *starting], enabled=enabled,
                bounds_for=bounds_for, fixed_offsets={key: offsets.get(key, 0.) for key in active})
            offsets.update((s.cue_id, layout.offsets.get(s.cue_id, 0.)) for s in starting)
            warnings.extend(layout.warnings)
            active.update((s.cue_id, s) for s in starting)
    return CollisionLayout(offsets, tuple(dict.fromkeys(warnings)))


class ProjectCollisionLayout:
    """Revision-indexed components, measured lazily once per overlap component."""
    def __init__(self):
        self.key = None
        self.components = {}
        self.layouts = {}

    def for_cues(self, project, cues, revision):
        cues = tuple(cues)
        if not project.studio_state.get('auto_subtitle_stacking', True):
            return CollisionLayout({})
        key = (revision.mapping_revision, revision.visual_revision,
               project.studio_state.get('auto_subtitle_stacking', True),
               tuple(sorted(project.studio_state.get('subtitle_track_visibility', {}).items())),
               tuple(s.id for s in project.speakers if getattr(s, 'hidden', False)))
        if key != self.key:
            from ..projects.studio_runtime_state import state_for
            from .subtitle_stacking import _cluster_overlaps
            rows = visible_subtitle_cues(project, state_for(project)._view_cues)
            self.components = {c.id: cluster for cluster in _cluster_overlaps(rows) for c in cluster}
            self.layouts = {}
            self.key = key
        offsets, warnings = {}, []
        from .bilingual_layout import project_display_cues, companion_id
        from .visual_snapshot import build_visual_cue_snapshot
        from copy import copy
        from types import SimpleNamespace
        import heapq
        target = max((c.start_ms for c in cues), default=-1)
        for cue in cues:
            cluster = self.components.get(cue.id)
            if cluster is None:
                offsets[cue.id] = 0.
                continue
            component = cluster[0].id
            if component not in self.layouts:
                self.layouts[component] = dict(cursor=0, active={}, offsets={}, endings=[], warnings=[])
            state = self.layouts[component]
            while state['cursor'] < len(cluster) and cluster[state['cursor']].start_ms <= target:
                at = cluster[state['cursor']].start_ms
                while state['endings'] and state['endings'][0][0] <= at:
                    _, key = heapq.heappop(state['endings'])
                    state['active'].pop(key, None)
                stop = state['cursor'] + 1
                while stop < len(cluster) and cluster[stop].start_ms == at:
                    stop += 1
                local = copy(project)
                local.cues = project_display_cues(project, cluster[state['cursor']:stop])
                local._studio_state_runtime = SimpleNamespace(cue_by_id={c.id: c for c in local.cues})
                snapshots = [build_visual_cue_snapshot(local, c.id) for c in local.cues]
                layout = solve_layout([*state['active'].values(), *snapshots],
                    enabled=project.studio_state.get('auto_subtitle_stacking', True),
                    fixed_offsets={key: state['offsets'][key] for key in state['active']})
                for snapshot in snapshots:
                    state['active'][snapshot.cue_id] = snapshot
                    state['offsets'][snapshot.cue_id] = layout.offsets.get(snapshot.cue_id, 0.)
                    heapq.heappush(state['endings'], (snapshot.end_ms, snapshot.cue_id))
                state['warnings'].extend(layout.warnings)
                state['cursor'] = stop
            for key in (cue.id, companion_id(cue.id)):
                if key in state['offsets']:
                    offsets[key] = state['offsets'][key]
            warnings.extend(state['warnings'])
        return CollisionLayout(offsets, tuple(dict.fromkeys(warnings)))


def project_layout_schedule(project, cues=None):
    """Export boundary only; preview already has indexed active prepared cues."""
    from .visual_snapshot import build_visual_cue_snapshot
    from types import SimpleNamespace
    from copy import copy
    local = copy(project)
    if cues is None:
        from .bilingual_layout import project_display_cues
        cues = project.cues if getattr(project, '_caption_display_materialized', False) else project_display_cues(project)
    local.cues = visible_subtitle_cues(project, cues)
    local._studio_state_runtime = SimpleNamespace(cue_by_id={c.id: c for c in local.cues})
    result = {c.id: [(c.start_ms, c.end_ms, 0.)] for c in local.cues}
    if not project.studio_state.get('auto_subtitle_stacking', True):
        return result
    from .subtitle_stacking import _cluster_overlaps
    for cluster in _cluster_overlaps(local.cues):
        snapshots = [build_visual_cue_snapshot(local, c.id) for c in cluster]
        result.update(layout_schedule(snapshots))
    return result


def visible_subtitle_cues(project, cues=None):
    """The subtitle eye is visibility; audio mute never hides caption ink."""
    hidden = {s.id for s in project.speakers if getattr(s, 'hidden', False)}
    hidden.update(key for key, shown in project.studio_state.get('subtitle_track_visibility', {}).items() if not shown)
    return [c for c in (project.cues if cues is None else cues) if c.speaker_id not in hidden]
