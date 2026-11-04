"""Sparse production-browser stills for temporally disjoint static/moving cues."""
from copy import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


def split_mixed_captions(project):
    """Conservative split: overlapping groups keep the authored single renderer.

    Static Qt export already exists for all-static projects. Here stills use
    Remotion itself, preserving the browser glyph metrics of mixed projects.
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
    if not static or not moving:
        return None
    spans = sorted([(c.start_ms, c.end_ms, 0) for c in static]
                   + [(c.start_ms, c.end_ms, 1) for c in moving])
    last_end = [-1, -1]
    for start, end, group in spans:
        if start < last_end[1-group]:
            return None
        last_end[group] = max(last_end[group], end)
    still_project, moving_project = copy(project), copy(project)
    still_project.cues = static
    wanted = {c.id for c in [*native, *moving]}
    moving_project.cues = [c for c in project.cues if c.id in wanted]
    return still_project, moving_project


def prepare_mixed_stills(project, root, folder, *, width, height, fps, start, duration,
                         cancelled=None, progress=None, trace=None):
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
        key = hashlib.sha256(json.dumps([fingerprint, width, height,
            [(cues[i]['text'], cues[i]['visual']) for i in sorted(active)]],
            sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()
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
            if progress and item.get('type') == 'still':
                progress(export_progress('advanced_render', message=f"静态字幕 {item['done']}/{item['total']}…",
                    percent=25*item['done']/item['total']))
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
    return sparse
