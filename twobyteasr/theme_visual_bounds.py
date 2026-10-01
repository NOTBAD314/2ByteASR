from .i18n import bind_text, tr
"""Measured full-animation HTML envelopes; never infer decoration size from text.

Calibration is explicit, offline and cached in the existing studio_state map.
The signature invalidates on text, style, transform, duration or canvas changes.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time


def measurement_key(cue, resolved, width, height, fps=30.):
    from .studio_revisions import thaw_json
    payload = [str(cue.text), int(cue.start_ms), int(cue.end_ms), resolved.recipe.to_dict(),
               thaw_json(cue.transform), int(width), int(height), float(fps)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def measured_bounds(project, cue, resolved, width, height):
    if not getattr(resolved.recipe, 'web_theme', {}):
        return None
    from .caption_frame_time import project_frame_rate
    fps = min(60., max(1., float(project_frame_rate(project) or 30)))
    value = project.studio_state.get('theme_visual_bounds', {}).get(measurement_key(cue, resolved, width, height, fps))
    if not isinstance(value, dict) or value.get('version') != 1:
        return None
    bounds = value.get('bounds')
    if not isinstance(bounds, list) or len(bounds) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds):
        return None
    return bounds


def calibrate_theme_bounds(project, *, output=None, progress=None, cancelled=None):
    from .advanced_renderer import compile_composition_data, split_renderer_cues
    from .caption_frame_time import project_frame_rate
    from .resolved_caption_style import resolve_caption_style
    from .renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob
    from .subtitle_stacking import _cluster_overlaps
    from .selection_geometry import alpha_bounds
    started = time.perf_counter()
    project = deepcopy(project)
    project.studio_state['auto_subtitle_stacking'] = False
    width = int(project.render_settings.get('play_res_x', 1920))
    height = int(project.render_settings.get('play_res_y', 1080))
    fps = min(60., max(1., float(project_frame_rate(project) or 30)))
    _, advanced = split_renderer_cues(project)
    overlapping = {cue.id for cluster in _cluster_overlaps(project.cues) for cue in cluster}
    selected = []
    for cue in advanced:
        resolved = resolve_caption_style(project.styles, project.speakers, cue, project.style_recipes, width)
        if cue.id in overlapping and resolved.recipe.web_theme:
            selected.append((cue, resolved))
    if len(selected) > 24:
        raise ValueError('本次存在超过 24 个重叠 HTML 字幕，请先选用较短工程或减少重叠主题。')
    results = {}
    receipt = dict(version=1, fps=fps, viewport=[width, height], cues=[], elapsed_seconds=0.)
    # Quarter-resolution alpha is a measuring instrument, never the saved
    # frame. A two-sample-pixel guard accounts for AA/shadow thresholds.
    ratio = min(1., 640/width)
    sample_width, sample_height = round(width*ratio), round(height*ratio)
    with tempfile.TemporaryDirectory(prefix='2byte-theme-bounds-') as scratch:
        folder = Path(scratch)
        for cue, resolved in selected:
            if cancelled and cancelled():
                raise InterruptedError('主题测量已取消。')
            key = measurement_key(cue, resolved, width, height, fps)
            if key in results:
                continue
            duration_ms = cue.end_ms-cue.start_ms
            if duration_ms > 15000:
                raise ValueError('重叠 HTML 字幕超过 15 秒，请分段后测量，避免长时间阻塞工作。')
            local = deepcopy(project)
            local.cues = [deepcopy(cue)]
            props = compile_composition_data(local, width=sample_width, height=sample_height, fps=fps,
                start_seconds=0, duration_seconds=cue.end_ms/1000)
            start_frame = max(0, math.ceil(cue.start_ms/1000*fps))
            end_frame = max(start_frame+1, math.ceil(cue.end_ms/1000*fps))
            count = end_frame-start_frame
            union = None
            # Batches bound disk/memory and provide cancellation points.
            for first in range(0, count, 30):
                jobs = [RendererJob(str(folder/f'{frame}.png'), props, start_frame+frame, job_kind='diagnostic')
                        for frame in range(first, min(first+30, count))]
                handle = GLOBAL_RENDERER_SERVICE.submit(jobs, render_type='still',
                    resolution=(sample_width, sample_height), timeout=90)
                while not handle._event.wait(.05):
                    if cancelled and cancelled():
                        handle.cancel()
                        raise InterruptedError('主题测量已取消。')
                result = handle.result(1)
                for job in jobs:
                    result.require_job(job)
                    path = Path(job.output)
                    box = alpha_bounds(path.read_bytes())
                    path.unlink()
                    if box:
                        x, y, w, h = box
                        edges = [x, y, x+w, y+h]
                        union = edges if union is None else [min(union[0], x), min(union[1], y), max(union[2], x+w), max(union[3], y+h)]
                if progress:
                    progress(f'正在测量主题装饰：{cue.id} · {min(first+30, count)}/{count} 帧')
            if union is None:
                raise ValueError(f'{cue.id}：主题在整个时段完全透明，无法测量。')
            guard = 2/ratio
            bounds = [union[0]/ratio-guard, union[1]/ratio-guard,
                      (union[2]-union[0])/ratio+2*guard, (union[3]-union[1])/ratio+2*guard]
            results[key] = dict(version=1, bounds=bounds, samples=count, fps=fps,
                                measure_viewport=[sample_width, sample_height], duration_ms=duration_ms)
            receipt['cues'].append(dict(cue_id=cue.id, key=key, **results[key]))
    receipt['elapsed_seconds'] = time.perf_counter()-started
    if output:
        Path(output).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return results, receipt


def start_studio_calibration(page):
    """Explicit right-click action; no rendering work in the layout hot path."""
    import threading
    from PySide6.QtGui import QUndoCommand
    from .cover_editor import CoverJob
    from .export_timeline import export_project_snapshot
    if not page.project or getattr(page, '_theme_bounds_busy', False):
        return
    page.video.set_paused(True)
    original = page.project
    snapshot = export_project_snapshot(original)
    # A content change during the worker invalidates the result instead of
    # applying stale bounds to a different project or later revision.
    from .studio_project import project_content_fingerprint
    fingerprint = project_content_fingerprint(original)
    page._theme_bounds_busy = True
    bind_text(page.save_state, tr('正在离线测量重叠 HTML 主题装饰…'))
    job = CoverJob(page)
    cancelled = threading.Event()
    page.destroyed.connect(lambda: cancelled.set())
    def finish(value):
        page._theme_bounds_busy = False
        job.deleteLater()
        if page.project is not original or project_content_fingerprint(original) != fingerprint:
            bind_text(page.save_state, tr('工程已改变，主题测量结果未应用；请重试。'))
            return
        results, receipt = value
        before = deepcopy(original.studio_state.get('theme_visual_bounds', {}))
        after = {**before, **results}
        class ApplyMeasurement(QUndoCommand):
            def __init__(self):
                super().__init__('测量主题装饰避让')
            def apply(self, data):
                original.studio_state['theme_visual_bounds'] = deepcopy(data)
                original._stack_layout_cache = None
                page._changed()
            def redo(self): self.apply(after)
            def undo(self): self.apply(before)
        if results:
            page.undo_stack.push(ApplyMeasurement())
        bind_text(page.save_state, tr('主题装饰测量完成：{value0} 个，{value1:.1f} 秒；改字或样式后需重新测量。', value0=len(results), value1=receipt['elapsed_seconds']))
        page._last_theme_bounds_receipt = receipt
    def fail(message):
        page._theme_bounds_busy = False
        job.deleteLater()
        bind_text(page.save_state, tr('主题装饰测量失败：{value0}；保持原位置，可手动调整。', value0=message))
    job.finished.connect(finish)
    job.failed.connect(fail)
    job.start(lambda: calibrate_theme_bounds(snapshot, cancelled=cancelled.is_set))
