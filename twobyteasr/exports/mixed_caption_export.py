"""Sparse production-browser stills for temporally disjoint static/moving cues."""
from copy import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


_HOLD_MOTION_KEYS = frozenset({'mode', 'origin', 'source', 'entry', 'entrance', 'exit', 'duration', 'outDuration'})


def hold_candidate(project, cue):
    """Entry/exit-only motion over otherwise static glyphs.

    Such a cue draws identical pixels between its entrance and its exit, so
    that hold can be one browser still instead of every frame (2026-11-19:
    with every caption animated, the browser rendered whole cue spans and
    exports ran at ~0.4x real time). Hold motion, glitch entrances, word
    timing, presets and effect IDs keep rendering every frame.
    """
    from ..rendering.advanced_renderer import recipe_payload_for_cue
    from .static_caption_contract import shared_static_recipe
    from ..caption_style.style_recipe import motion_mode
    if cue.effect_id not in ('', 'none', None):
        return False
    recipe = recipe_payload_for_cue(project, cue) or {}
    motion = recipe.get('motion') or {}
    if not isinstance(motion, dict) or motion_mode(motion) == 'none' or set(motion) - _HOLD_MOTION_KEYS:
        return False
    entry = motion.get('entrance') or motion.get('entry') or {}
    entry_type = str(entry.get('type') if isinstance(entry, dict) else entry or '')
    if 'glitch' in entry_type or entry_type == 'slam':
        return False
    return shared_static_recipe(dict(recipe, motion={'mode': 'none'}))


def _js_round(value):
    return math.floor(value + .5)


def hold_window(props_cue, fps):
    """Composition frames (first, last) where TrustedSubtitle's pixels are constant.

    Mirrors SubtitleComposition/TrustedSubtitle: localFrame = frame -
    round(startMs*fps) + localOffsetMs*fps; entryProgress reaches 1 at
    entranceFrames and exitProgress leaves 0 after durationFrames-exitFrames.
    One frame of margin on each side; None when anything else may vary.
    """
    visual = props_cue.get('visual') or {}
    if visual.get('webTheme') or visual.get('visualGraph'):
        return None
    words = visual.get('wordAnimation') or {}
    if words.get('spans') or words.get('units') or words.get('marks'):
        return None
    if 'scanline' in (visual.get('decorations') or ()):
        return None
    motion = visual.get('motion') or {}
    entrance, exit_, hold = (motion.get(k) or {} for k in ('entrance', 'exit', 'hold'))
    def kind(part, fallback='none'):
        value = part.get('type') if isinstance(part, dict) else None
        return str(value) if isinstance(value, str) and value else fallback
    entrance_type = kind(entrance, motion.get('entry') if isinstance(motion.get('entry'), str) else 'none')
    exit_type, hold_type = kind(exit_), kind(hold)
    if hold_type != 'none' or 'glitch' in entrance_type or entrance_type == 'slam':
        return None
    enabled = motion.get('mode') == 'explicit' or (motion.get('mode') is None and (entrance_type != 'none' or exit_type != 'none'))
    def number(part, key, fallback):
        value = part.get(key) if isinstance(part, dict) else None
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else float(fallback)
    entrance_frames = max(1, _js_round(number(entrance, 'duration_ms', motion.get('duration') if isinstance(motion.get('duration'), (int, float)) else 240)/1000*fps)) \
        if enabled and entrance_type != 'none' else 0
    exit_frames = max(1, _js_round(number(exit_, 'duration_ms', 160)/1000*fps)) if enabled and exit_type != 'none' else 0
    start_frame = _js_round(props_cue['startMs']/1000*fps)
    offset = (props_cue.get('localOffsetMs') or 0)/1000*fps
    duration_frames = max(1, _js_round((props_cue.get('cueDurationMs') or (props_cue['endMs']-props_cue['startMs']))/1000*fps))
    rate = Fraction(str(fps)).limit_denominator(100100)
    visible_first = math.ceil(Fraction(props_cue['startMs'], 1000)*rate)
    visible_last = math.ceil(Fraction(props_cue['endMs'], 1000)*rate) - 1
    first = max(visible_first, math.ceil(start_frame + entrance_frames - offset) + 1)
    last = min(visible_last, math.floor(start_frame + duration_frames - exit_frames - offset) - 1)
    return (first, last) if last - first + 1 >= 4 else None


def split_mixed_captions(project):
    """Conservative split: overlapping groups keep the authored single renderer.

    Static Qt export already exists for all-static projects. Here stills use
    Remotion itself, preserving the browser glyph metrics of mixed projects.
    Isolated entry/exit-only cues (``hold_candidate``) are in both projects:
    the still project draws their hold, the moving project their entrance
    and exit windows (see ``hold_window``).
    """
    from ..rendering.advanced_renderer import split_renderer_cues, recipe_payload_for_cue
    from .static_caption_contract import shared_static_cue
    native, advanced = split_renderer_cues(project)
    # WebThemeStage is composition-wide, including gaps and other cue styles.
    # Disjoint cue spans do not prove that its ambient layer may be shortened.
    if any((recipe_payload_for_cue(project, c) or {}).get('webTheme')
           or (recipe_payload_for_cue(project, c) or {}).get('web_theme') for c in advanced):
        return None
    static, moving = [], []
    for cue in advanced:
        (static if shared_static_cue(project, cue) else moving).append(cue)
    from ..caption_style.collision_layout import project_layout_schedule
    schedule=project_layout_schedule(project)
    ordered = sorted(advanced, key=lambda c: (c.start_ms, c.end_ms))
    candidates = {c.id for c in moving if len(schedule.get(c.id, ((c.start_ms, c.end_ms, 0.),))) == 1
                  and hold_candidate(project, c)}
    def isolated(cue):
        # A bilingual companion shares its source's exact span; such a group
        # holds and animates together (render() checks equal hold frames).
        return all(other is cue or other.end_ms <= cue.start_ms or other.start_ms >= cue.end_ms
                   or (other.id in candidates and (other.start_ms, other.end_ms) == (cue.start_ms, cue.end_ms))
                   for other in ordered)
    holds = [c for c in moving if c.id in candidates and isolated(c)]
    hold_ids = {c.id for c in holds}
    if not moving or not (static or holds):
        return None
    spans = sorted([(c.start_ms, c.end_ms, 0) for c in static]
                   + [(c.start_ms, c.end_ms, 1) for c in moving if c.id not in hold_ids])
    last_end = [-1, -1]
    for start, end, group in spans:
        if start < last_end[1-group]:
            return None
        last_end[group] = max(last_end[group], end)
    still_project, moving_project = copy(project), copy(project)
    still_project._subtitle_layout_schedule=schedule
    moving_project._subtitle_layout_schedule=schedule
    still_project.cues = [c for c in project.cues if c.id in {x.id for x in static} | hold_ids]
    wanted = {c.id for c in [*native, *moving]}
    moving_project.cues = [c for c in project.cues if c.id in wanted]
    still_project._hold_cue_ids = moving_project._hold_cue_ids = frozenset(hold_ids)
    return still_project, moving_project


def prepare_mixed_stills(project, root, folder, *, width, height, fps, start, duration,
                         cancelled=None, progress=None, trace=None, render_stills=None, holds=None):
    """``holds``: cue id -> (first, last) output frames drawn as a still.

    Hold candidates without an entry here are left entirely to the moving
    windows; every other cue keeps its whole span.
    """
    holds = dict(holds or {})
    hold_ids = getattr(project, '_hold_cue_ids', frozenset())
    from PIL import Image
    from ..rendering.advanced_renderer import (compile_composition_data, _composition_browser,
        _export_browser, _run_streaming_process, _renderer_cache_fingerprint, _overlay_cache_dir,
        _copy_verified_overlay, _cache_overlay, _trim_overlay_cache)
    from ..system.processes import renderer_node_command
    from .static_caption_timeline import build_caption_timeline
    from .studio_render import export_progress
    from .export_failure import renderer_failure
    from .export_performance import export_phase
    folder, root = Path(folder), Path(root)
    props = compile_composition_data(project, width=width, height=height, fps=fps,
                                     start_seconds=start, duration_seconds=duration)
    rate = Fraction(str(fps)).limit_denominator(100100)
    props_path = folder / 'static-recipes.json'
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding='utf8')
    pending, paths, scenes, scene_cues = [], {}, [], {}
    fingerprint = _renderer_cache_fingerprint()
    events = {0: [], props['durationInFrames']: []}
    cues = props['cues']
    for index, cue in enumerate(cues):
        source = cue.get('sourceId', cue['id'])
        if source in hold_ids:
            if source not in holds:
                continue
            first, last = holds[source][0], min(props['durationInFrames'], holds[source][1] + 1)
        else:
            first = max(0, math.ceil(Fraction(cue['startMs'], 1000)*rate))
            last = min(props['durationInFrames'], math.ceil(Fraction(cue['endMs'], 1000)*rate))
        if first < last:
            events.setdefault(first, []).append((index, True))
            events.setdefault(last, []).append((index, False))
    active = set()
    boundaries = sorted(events)
    for position, first in enumerate(boundaries[:-1]):
        for index, enabled in events[first]:
            if enabled:active.add(index)
            else:active.discard(index)
        if not active:continue
        last = boundaries[position+1]
        from ..rendering.caption_asset_identity import asset_key
        key = asset_key(props, first, first, still=True,fingerprint=fingerprint)
        scenes.append((key, first, last))
        scene_cues[key] = [cues[i]['id'] for i in sorted(active)]
        if key in paths:continue
        output = folder / f'still-{len(paths)}.png'
        paths[key] = output
        if not _copy_verified_overlay(_overlay_cache_dir() / (key+'.still.png'), output):
            pending.append(dict(output=str(output), frame=first))
    if pending:
        manifest = folder / 'static-manifest.json'
        manifest.write_text(json.dumps(dict(props=str(props_path), stills=pending,
            browser=str(_composition_browser(root, props)), referenceBrowser=str(_export_browser(root, web=False)))),
            encoding='utf8')
        def line(value):
            try:
                item = json.loads(value)
            except ValueError:
                return
            if trace and item.get('type') != 'still': trace('browser_renderer_stage', item)
            if progress and item.get('type') == 'still':
                progress(export_progress('advanced_render', message=f"静态字幕 {item['done']}/{item['total']}…",
                    percent=25*item['done']/item['total']))
        if render_stills:
            # The caller can render static and moving batches in one owned
            # browser. Caching, alpha bounds and sparse scheduling stay here.
            render_stills(manifest, line)
        else:
            with export_phase('mixed_static_stills', requested=len(props['cues']), rendered=len(pending)):
                code, logs = _run_streaming_process([*renderer_node_command(root, root/'render-caption-stills.mjs'), str(manifest)],
                    cwd=root, on_line=line, cancelled=cancelled, stall_timeout=120)
            if code:
                raise renderer_failure(code, logs)
    layers, cropped = [], {}
    for key, first, last in scenes:
        if cancelled and cancelled():raise InterruptedError('render cancelled')
        image_path = paths[key]
        if key not in cropped:
            with Image.open(image_path) as image:
                # A whole static active set uses the original browser layer
                # order (including bilingual companions), then crops losslessly.
                bounds = image.getchannel('A').getbbox()
                if bounds is None:
                    from .static_caption_contract import intentional_empty_reason
                    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
                    if not all(intentional_empty_reason(build_visual_cue_snapshot(project, cue_id,
                        width=width, height=height, fps=fps)) for cue_id in scene_cues[key]):
                        raise RuntimeError('静态字幕场景像素为空')
                    cropped[key] = (None, None)
                    continue
                target = folder / (image_path.stem+'-crop.png')
                image.crop(bounds).save(target, compress_level=1)
            try:_cache_overlay(image_path, _overlay_cache_dir() / (key+'.still.png'))
            except OSError:pass
            cropped[key] = (target, bounds)
        target, bounds = cropped[key]
        if target is None:continue
        layers.append(dict(path=target, bounds=bounds, start=float(first/rate), end=float(last/rate),
                           first_frame=first, last_frame=last))
    _trim_overlay_cache()
    with export_phase('mixed_static_schedule', captions=len(layers)):
        sparse = build_caption_timeline(layers, folder, fps=fps, duration=duration, cancelled=cancelled)
    if trace:
        trace('mixed_static_captions', dict(captions=len(layers), rendered_stills=len(pending),
            cache_hits=len(paths)-len(pending), scenes=sparse['scenes']))
    sparse['asset_cache']=dict(total=len(paths),rendered=len(pending),hits=len(paths)-len(pending))
    # Cropped browser stills per scene (canvas bounds, output frames): the
    # native entrance/exit renderer derives held cues' moving frames from them.
    sparse['layers']=layers
    return sparse
