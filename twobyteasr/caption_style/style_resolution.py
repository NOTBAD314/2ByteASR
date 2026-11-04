"""Canonical appearance and transform resolution for one subtitle cue."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..projects.studio_project import StudioCue, SubtitleProject, SubtitleStyle


APPEARANCE_FIELDS = frozenset({
    "font_family", "font_size", "primary_color", "outline_color",
    "outline_width", "outline2_color", "outline2_width", "shadow",
    "bold", "italic", "underline", "back_color", "border_style", "spacing",
    "font_style_name", "font_weight", "font_file", "font_face_index",
})
TRANSFORM_FIELDS = frozenset({
    "position_x", "position_y", "scale_x", "scale_y", "rotation", "font_size",
    "alignment", "margin_l", "margin_r", "margin_v",
})


@dataclass(frozen=True)
class ResolvedCueVisual:
    style: SubtitleStyle
    appearance_override: Mapping[str, Any]
    transform: Mapping[str, Any]


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    items = getattr(value, "items", None)
    if isinstance(items, tuple):
        result: dict[str, Any] = {}
        for key, item in items:
            nested = getattr(item, "items", None)
            result[str(key)] = _payload(item) if isinstance(nested, tuple) else copy.deepcopy(item)
        return result
    return {}


def resolve_cue_visual(project: SubtitleProject, cue: StudioCue) -> ResolvedCueVisual:
    return resolve_cue_visual_from_records(project.styles, project.speakers, cue)


def recipe_for_cue(recipes, cue):
    """A display language layer may carry a private, sparse recipe patch."""
    from .style_recipe import recipe_payload_for_style
    payload = recipe_payload_for_style(recipes, cue.style_id)
    appearance = _payload(getattr(cue, 'appearance_override', {}))
    if '_recipe_base' in appearance: payload = appearance['_recipe_base'] or None
    patch = appearance.get('_recipe_patch')
    if not patch:
        return payload
    from .scoped_style import merge_patch
    result = merge_patch(payload or {'name': '语言层样式'}, patch)
    return result


def resolve_cue_visual_from_records(
    style_records: Sequence[SubtitleStyle],
    speaker_records: Sequence[Any],
    cue: Any,
) -> ResolvedCueVisual:
    styles = {item.id: item for item in style_records}
    # Preset identity is authoritative and intentionally independent from the
    # materialized style/recipe key. A derived or AI style_id may carry motion
    # and graph data, but it must never become a second appearance base.
    base_preset_id = str(getattr(cue, "base_preset_id", "") or "").strip()
    base = styles.get(base_preset_id) if base_preset_id else None
    if base is None:
        base = styles.get(cue.style_id)
    if base is None:
        speaker_styles = {item.id: item.style_id for item in speaker_records}
        base = styles.get(speaker_styles.get(cue.speaker_id, "default"), styles["default"])
    if isinstance(base, SubtitleStyle):
        style = copy.deepcopy(base)
    else:
        style = SubtitleStyle(**{
            field: copy.deepcopy(getattr(base, field))
            for field in SubtitleStyle.__dataclass_fields__
        })
    # A scoped/AI-derived style is still anchored to ``base_preset_id`` for
    # appearance resolution, but it may carry explicit layout values created
    # by the inspector (position, alignment, margins, scale).  Preserve those
    # values here so ASS, LIVE, Fidelity, and transform geometry share one
    # layout truth without turning the derived style into a second appearance
    # preset.
    derived = styles.get(getattr(cue, "style_id", ""))
    if derived is not None and derived.id != getattr(base, "id", ""):
        for name in (
            "position_x", "position_y", "scale_x", "scale_y", "alignment",
            "margin_l", "margin_r", "margin_v",
        ):
            if hasattr(derived, name):
                setattr(style, name, copy.deepcopy(getattr(derived, name)))
    appearance = _payload(getattr(cue, "appearance_override", {}))
    transform = _payload(getattr(cue, "transform", {}))
    # Initial overlap layout is saved once, in video coordinates.  An explicit
    # cue/track edit below overrides it; rendering never reallocates its row.
    initial = transform.get("initial_layout", {})
    if isinstance(initial, Mapping) and initial.get("version") == 1:
        for name in ("position_x", "position_y"):
            value = initial.get(name)
            if isinstance(value, (int, float)):
                setattr(style, name, value)
    for name, value in appearance.items():
        if name in APPEARANCE_FIELDS and hasattr(style, name):
            setattr(style, name, copy.deepcopy(value))
    for name, value in transform.items():
        if name in TRANSFORM_FIELDS and name != "rotation" and hasattr(style, name):
            setattr(style, name, copy.deepcopy(value))
    style.validate()
    if transform.get('_canvas_transform'):
        # Legacy SubtitleStyle clamps anchors to nonnegative integer pixels.
        # Explicit layer transforms use finite project coordinates (including
        # off-canvas and subpixel positions), shared with video transforms.
        import math
        for name in ('position_x','position_y'):
            value=transform.get(name)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                setattr(style,name,float(value))
    return ResolvedCueVisual(
        style=style,
        appearance_override=appearance,
        transform=transform,
    )


def appearance_overrides_for_style(
    base: SubtitleStyle,
    effective: SubtitleStyle,
) -> dict[str, Any]:
    """Return only explicit appearance differences from a preset base."""

    overrides: dict[str, Any] = {}
    for name in APPEARANCE_FIELDS:
        if not hasattr(base, name) or not hasattr(effective, name):
            continue
        value = getattr(effective, name)
        if value != getattr(base, name):
            overrides[name] = copy.deepcopy(value)
    return overrides
