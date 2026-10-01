"""Deterministic overlap stacking for simultaneous cues.

Two speakers talking over each other used to render both cues at the same
anchor (bottom-center default), painting one on top of the other. This module
computes a pure per-cue display offset — earlier cue stays lowest, each later
cue stacks above the heights of everything below it — and never writes back
into user styles, cue transforms or recipes.

The offset is a *display layout result*: it depends only on (cue set, texts,
resolved styles, play resolution), so preview, seek and export all agree.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

# Same magnitude as the bilingual secondary line spacing in ass_compiler
# (font_size * 1.06); extra room for outline/shadow bleed.
_STACK_GAP_FACTOR = 1.12
_OUTLINE_SLAB = 2.0
# Never push stacked captions above this fraction of the play height.
_TOP_SAFETY = 0.12
# Cues that overlap for less than this are effectively sequential; leave both
# at their authored anchors (avoids a visible hop for 1-frame collisions).
_MIN_OVERLAP_MS = 60


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
    """(height_px, gap_px) of one cue from its resolved caption measurement.

    ``resolved`` is a ResolvedCaptionStyle (read-only measurement contract):
    height = line_count * line_height * scale_y + outline/shadow allowance;
    the gap between stack rows follows the bilingual-line precedent
    (own font size * factor). StyleRecipe.layout is a plain dict.
    """
    style = resolved.style
    layout = dict(resolved.recipe.layout or {})
    line_count = max(1, int(resolved.line_count or layout.get("lineCount") or 1))
    line_height = float(layout.get("lineHeightPx") or 0.0)
    if line_height <= 0.0:
        line_height = float(style.font_size) * 1.16
    scale_y = max(0.05, float(style.scale_y or 100.0) / 100.0)
    slab = max(float(style.outline_width or 0.0), float(getattr(style, "outline2_width", 0.0) or 0.0))
    slab = max(slab, float(style.shadow or 0.0))
    height = line_count * line_height * scale_y + slab * _OUTLINE_SLAB
    gap = float(style.font_size or 20.0) * _STACK_GAP_FACTOR
    return height, gap


def compute_stack_layout(cues, *, resolve_one, play_res_y, enabled=True, play_res_x=1920, effect_for=None, bounds_for=None):
    """Allocate stable spatial positions for each full cue lifetime.

    Only temporally overlapping rectangles reserve space. A later cue keeps
    its allocated position after peers finish; nonoverlapping peers reuse it.
    Fixed authored positions are obstacles, never moved by this operation.
    """
    if not enabled:return StackLayout({})
    offsets, warnings = {}, []
    for cluster in _cluster_overlaps(list(cues)):
        placed=[]
        def fixed(c):
            transform=getattr(c,'transform',{})
            if not isinstance(transform,dict):
                from .studio_revisions import thaw_json
                transform=thaw_json(transform)
            return bool(transform.get('position_locked') or
                        any(k in transform for k in ('position_x','position_y')))
        ordered=sorted(cluster,key=lambda c:(not fixed(c),c.start_ms,c.speaker_id if hasattr(c,'speaker_id') else '',c.id))
        for cue in ordered:
            try:
                resolved=resolve_one(cue)
                if resolved is None:continue
                style=resolved.style
                height,gap=_cue_stack_metrics(resolved)
                gap=max(8.,float(style.font_size)*.18)
                recipe=resolved.recipe
                shadow=(getattr(recipe,'outline',{}) or {}).get('shadow',{}) or {}
                extra=max(abs(float(shadow.get('offsetY',shadow.get('offset_y',0)) or 0)),0)
                extra+=float(shadow.get('blur',0) or 0)*2+float(shadow.get('spread',0) or 0)*2
                height+=extra
                glow=(getattr(recipe,'effects',{}) or {}).get('glow',{}) or {}
                height+=float(glow.get('blur',0) or 0)*2
                background=getattr(recipe,'background',{}) or {}
                if isinstance(background,dict) and background.get('enabled'):
                    height+=float(background.get('paddingY',background.get('padding',0)) or 0)*2
                width=min(float(play_res_x),float(getattr(resolved,'measured_width',play_res_x*.8)))
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
                original_bottom=bottom
                obstacles=[r for other,r in placed if _pair_overlap_ms(cue,other)>0]
                def collision(rect):
                    return left<rect[2] and right>rect[0] and top<rect[3]+gap and bottom>rect[1]-gap
                if not fixed(cue):
                    for _ in range(len(obstacles)+1):
                        hits=[r for r in obstacles if collision(r)]
                        if not hits:break
                        bottom=min(r[1] for r in hits)-gap;top=bottom-height
                    if top<play_res_y*.03:
                        # No silent font reduction or clipping. Preserve the
                        # authored placement and expose a recoverable warning.
                        warnings.append(f'{cue.id}:画面高度不足，请调整字号或固定位置')
                        bottom=original_bottom;top=bottom-height
                elif any(collision(r) for r in obstacles):
                    warnings.append(f'{cue.id}:固定位置发生遮挡，请移动字幕或解除固定')
                offset=original_bottom-bottom
                if abs(offset)>.5:offsets[str(cue.id)]=round(offset,1)
                placed.append((cue,(left,top,right,bottom)))
            except Exception as exc:
                warnings.append(f'{cue.id}:无法测量字幕布局: {type(exc).__name__}')
    return StackLayout(offsets,tuple(warnings))


def project_stack_layout(project):
    from .studio_edit_sequence import projected_cues
    from .resolved_caption_style import resolve_caption_style
    runtime=getattr(project,'_studio_state_runtime',None)
    immutable=project.render_settings.get('_cue_domain')=='timeline'
    key=(getattr(runtime,'revision',None),project.studio_state.get('auto_subtitle_stacking',True))
    if not immutable and runtime is None:
        key+=(repr(project.cues),repr(project.styles),repr(project.style_recipes),repr(project.studio_state))
    cached=getattr(project,'_stack_layout_cache',None)
    if cached and cached[0]==key:return cached[1]
    cues=projected_cues(project)
    width=int(project.render_settings.get('play_res_x',1920))
    try:
        from .theme_visual_bounds import measured_bounds
        layout=compute_stack_layout(cues,resolve_one=lambda c:resolve_caption_style(project.styles,project.speakers,c,project.style_recipes,width),
            play_res_y=int(project.render_settings.get('play_res_y',1080)),play_res_x=width,
            enabled=project.studio_state.get('auto_subtitle_stacking',True),
            effect_for=lambda c:project.effects.get(c.effect_id,{}),
            bounds_for=lambda c,resolved:measured_bounds(project,c,resolved,width,int(project.render_settings.get('play_res_y',1080))))
    except Exception as exc:
        layout=StackLayout({},(f'自动避让暂不可用：{type(exc).__name__}，可调整固定位置',))
    project._stack_layout_cache=(key,layout)
    return layout
