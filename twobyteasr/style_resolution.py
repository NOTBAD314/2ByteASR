"""Canonical appearance and transform resolution for one subtitle cue."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .studio_project import StudioCue, SubtitleProject, SubtitleStyle


APPEARANCE_FIELDS = frozenset({
    "font_family", "font_size", "primary_color", "outline_color",
    "outline_width", "outline2_color", "outline2_width", "shadow",
    "bold", "italic", "underline", "back_color", "border_style", "spacing",
    "font_style_name", "font_weight", "font_file", "font_face_index",
})
TRANSFORM_FIELDS = frozenset({
    "position_x", "position_y", "scale_x", "scale_y", "rotation", "font_size",
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
    for name, value in appearance.items():
        if name in APPEARANCE_FIELDS and hasattr(style, name):
            setattr(style, name, copy.deepcopy(value))
    for name, value in transform.items():
        if name in TRANSFORM_FIELDS and name != "rotation" and hasattr(style, name):
            setattr(style, name, copy.deepcopy(value))
    style.validate()
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
