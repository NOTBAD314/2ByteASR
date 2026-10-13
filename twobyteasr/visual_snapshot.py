"""Authoritative, read-only visual state for one Studio cue.

The project remains the persistence boundary.  This module only resolves the
effective cue/style/recipe once so Native preview proxies, Remotion previews,
and final export cannot independently reinterpret the same subtitle.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Any, Mapping

from .studio_project import SubtitleProject, SubtitleStyle, StudioCue
from .style_resolution import resolve_cue_visual
from .style_recipe import (
    MOTION_MODE_NONE,
    FillSpec,
    MotionRecipe,
    StyleRecipe,
    motion_mode,
    normalize_glow_contract,
    normalize_motion_contract,
    normalize_shadow_contract,
    normalize_stroke_alignment,
    recipe_payload_for_style,
)


@dataclass(frozen=True)
class VisualCueSnapshot:
    cue_id: str
    text: str
    start_ms: int
    end_ms: int
    font_family: str
    font_size: float
    font_weight: int
    italic: bool
    letter_spacing: float
    fill: object
    strokes: tuple[dict[str, Any], ...]
    shadow: dict[str, Any]
    glow: dict[str, Any]
    playres_x: int
    playres_y: int
    position_x: float
    position_y: float
    alignment: int
    anchor_x: float
    anchor_y: float
    scale_x: float
    scale_y: float
    rotation: float
    style_recipe: dict[str, Any]
    motion_recipe: dict[str, Any]
    speaker: str
    resolution: tuple[int, int]
    fps: float
    appearance_generation: int
    project_id: str = ""
    translation: str = ""
    resolved_caption: object = None

    def to_dict(self) -> dict[str, Any]:
        # dataclasses.asdict already recursively copies every mutable field.
        return asdict(self)

    def stable_hash(self) -> str:
        # Hash reads without copying: serialization cannot mutate the snapshot.
        # Nested edits remain observable, unlike a cache keyed by object id.
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        # The generation is a commit-order token, not rendered content.  It is
        # compared independently by AdvancedPreviewIdentity so undo can return
        # to a byte-identical visual snapshot without accepting an older job.
        payload.pop("appearance_generation", None)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
            default=lambda value: asdict(value) if is_dataclass(value) else str(value),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def glyph_hash(self) -> str:
        """Hash raster glyph inputs; transform, timing and motion stay separate."""
        effects = self.style_recipe.get("effects", {}) if isinstance(self.style_recipe, Mapping) else {}
        background = self.style_recipe.get("background", {}) if isinstance(self.style_recipe, Mapping) else {}
        payload = {
            "text": self.text,
            "translation": getattr(self, "translation", ""),
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_weight": self.font_weight,
            "italic": self.italic,
            "letter_spacing": self.letter_spacing,
            "fill": self.fill,
            "strokes": self.strokes,
            "shadow": self.shadow,
            "glow": self.glow,
            "decorations": background.get("marks", []),
            "effects": effects,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def pixel_hash(
        self,
        *,
        renderer_version: str = "visual-pixel-v1",
        resolution: tuple[int, int] | None = None,
        device_pixel_ratio: float = 1.0,
    ) -> str:
        """Hash every static input that can change the rendered pixels."""
        recipe = self.style_recipe if isinstance(self.style_recipe, Mapping) else {}
        colors = recipe.get("colors", {}) if isinstance(recipe.get("colors", {}), Mapping) else {}
        payload = {
            "renderer": str(renderer_version),
            "text": self.text,
            "font": {
                "family": self.font_family,
                "size": self.font_size,
                "weight": self.font_weight,
                "italic": self.italic,
                "letter_spacing": self.letter_spacing,
            },
            "fill": self.fill,
            "strokes": self.strokes,
            "shadow": self.shadow,
            "glow": self.glow,
            # These are the recipe sections the fidelity normalizer consumes
            # beyond the canonical fields above. Exclude names, ASS metadata,
            # and motion so unrelated state cannot invalidate a static frame.
            "recipe_pixels": {
                "background": recipe.get("background", {}),
                "effects": recipe.get("effects", {}),
                "background_color": colors.get("background"),
            },
            "layout": {
                "playres": (self.playres_x, self.playres_y),
                "position": (self.position_x, self.position_y),
                "alignment": self.alignment,
                "anchor": (self.anchor_x, self.anchor_y),
                "scale": (self.scale_x, self.scale_y),
                "rotation": self.rotation,
            },
            "resolution": tuple(resolution or self.resolution),
            "device_pixel_ratio": round(max(0.1, float(device_pixel_ratio)), 3),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def motion_hash(self) -> str:
        encoded = json.dumps(
            {"glyph": self.glyph_hash(), "motion": self.motion_recipe},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def geometry_signature(self) -> tuple[object, ...]:
        """Fields a fill-only edit is forbidden to mutate."""
        return (
            self.playres_x, self.playres_y, self.position_x, self.position_y,
            self.alignment, self.anchor_x, self.anchor_y, self.scale_x,
            self.scale_y, self.rotation, self.font_size,
        )


def _effective_style(project: SubtitleProject, cue: StudioCue) -> SubtitleStyle:
    return resolve_cue_visual(project, cue).style


def _materialize_recipe_appearance(
    recipe: StyleRecipe,
    style: SubtitleStyle,
    appearance_override: Mapping[str, Any],
) -> StyleRecipe:
    """Synchronize every renderer-facing appearance field from one resolve.

    Motion, panels, decorations and effects stay owned by the recipe. Glyph
    appearance is always rewritten from ``preset + explicit overrides`` so an
    old VisualGraph cannot restore a stale or empty stroke list.
    """

    recipe.typography.update({
        "fontFamily": style.font_family,
        "fontSize": style.font_size,
        "bold": style.bold,
        "fontWeight": style.font_weight, "fontStyleName": style.font_style_name,
        "italic": style.italic,
        "spacing": style.spacing,
        "scaleX": style.scale_x,
        "scaleY": style.scale_y,
    })
    recipe.layout.update({
        "alignment": style.alignment,
        "marginL": style.margin_l,
        "marginR": style.margin_r,
        "marginV": style.margin_v,
        "positionX": style.position_x,
        "positionY": style.position_y,
    })
    existing_fill = recipe.colors.get("fill")
    keep_gradient = (
        isinstance(existing_fill, Mapping)
        and str(existing_fill.get("type") or "solid").casefold() != "solid"
    )
    if not keep_gradient:
        recipe.colors["fill"] = style.primary_color
    recipe.colors["outline"] = style.outline_color
    recipe.colors["background"] = style.back_color

    strokes = copy.deepcopy(style.stroke_layers())
    recipe.outline["color"] = style.outline_color
    recipe.outline["width"] = style.outline_width
    recipe.outline["layers"] = strokes
    existing_shadow = recipe.outline.get("shadow")
    if "shadow" in appearance_override or not (
        isinstance(existing_shadow, Mapping) and existing_shadow
    ):
        canonical_shadow = normalize_shadow_contract(style.shadow)
    else:
        # Advanced recipes can express blur/spread/offset independently while
        # SubtitleStyle retains only its native scalar fallback. Preserve that
        # one rich recipe contract until the user explicitly edits Shadow.
        canonical_shadow = normalize_shadow_contract(existing_shadow)
    recipe.outline["shadow"] = canonical_shadow
    recipe.background.update({
        "enabled": style.border_style == 3,
        "color": style.back_color,
    })

    if isinstance(recipe.visual_graph, Mapping) and recipe.visual_graph:
        graph = copy.deepcopy(dict(recipe.visual_graph))
        text_layer = graph.get("textLayer")
        if isinstance(text_layer, dict):
            font = text_layer.setdefault("font", {})
            if isinstance(font, dict):
                font.update({
                    "family": style.font_family,
                    "size": style.font_size,
                    "weight": style.font_weight or (700 if style.bold else 400),
                    "italic": style.italic,
                })
            text_layer["strokes"] = copy.deepcopy(strokes)
            text_layer["shadow"] = copy.deepcopy(canonical_shadow)
            text_layer["letterSpacing"] = style.spacing
            text_layer["alignment"] = style.alignment
            graph_fill = text_layer.get("fill")
            graph_has_gradient = (
                isinstance(graph_fill, Mapping)
                and str(graph_fill.get("type") or "solid").casefold() != "solid"
            )
            if not graph_has_gradient:
                text_layer["fill"] = {
                    "type": "solid",
                    "color": style.primary_color,
                }
        recipe.visual_graph = graph
    return recipe


def _anchor(style: SubtitleStyle, playres_x: int, playres_y: int) -> tuple[float, float, float, float]:
    column = (int(style.alignment) - 1) % 3
    row = (int(style.alignment) - 1) // 3
    horizontal = (style.margin_l, playres_x / 2, playres_x - style.margin_r)
    vertical = (playres_y - style.margin_v, playres_y / 2, style.margin_v)
    x = float(style.position_x if style.position_x is not None else horizontal[column])
    y = float(style.position_y if style.position_y is not None else vertical[row])
    return x, y, (0.0, 0.5, 1.0)[column], (1.0, 0.5, 0.0)[row]


def _cue_translation(project: SubtitleProject, cue_id: str) -> str:
    """Second-language text for the cue (bilingual video layer)."""
    metadata = getattr(project, "generation_metadata", None)
    if not isinstance(metadata, Mapping):
        return ""
    translations = metadata.get("translations")
    if not isinstance(translations, Mapping):
        return ""
    return str(translations.get(cue_id, "") or "")


def build_visual_cue_snapshot(
    project: SubtitleProject,
    cue_id: str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: float = 30.0,
) -> VisualCueSnapshot:
    runtime = getattr(project, '_studio_state_runtime', None)
    cue = runtime.cue_by_id.get(cue_id) if runtime is not None else None
    if cue is None:
        # 2026-09-19 P0：剪辑视图的派生 id（"源id#段id"）解析回源 cue；
        # 视图重建间隙里已消失的陈旧 id 返回 None（预热器跳过即可）。
        from .studio_edit_sequence import source_cue_id_of
        resolved_id = source_cue_id_of(str(cue_id))
        cue = next((item for item in project.cues if item.id == cue_id), None)
        if cue is None:
            cue = next((item for item in project.cues if item.id == resolved_id), None)
    if cue is None:
        return None
    # Web-theme previews and renders show the project's punctuation choice.
    from .punctuation_style import style_cues
    cue = style_cues(project, [cue])[0]
    resolved = resolve_cue_visual(project, cue)
    style = resolved.style
    from .resolved_caption_style import resolve_caption_style
    caption = resolve_caption_style(project.styles, project.speakers, cue,
        project.style_recipes, int(project.render_settings.get("play_res_x", 1920)))
    style = caption.style
    style_ids = {item.id for item in project.styles}
    appearance_base_resolved = bool(
        str(cue.base_preset_id or "") in style_ids or str(cue.style_id or "") in style_ids
    )
    playres_x = max(1, int(project.render_settings.get("play_res_x", 1920)))
    playres_y = max(1, int(project.render_settings.get("play_res_y", 1080)))
    output_width = max(1, int(width or project.media.width or playres_x))
    output_height = max(1, int(height or project.media.height or playres_y))
    payload = recipe_payload_for_style(project.style_recipes, cue.style_id)
    if payload:
        recipe = StyleRecipe.from_dict(payload)
    else:
        recipe = StyleRecipe(
            name=style.name,
            typography={}, colors={"fill": style.primary_color},
            outline={"color": style.outline_color, "width": style.outline_width},
            motion={},
        )
    # Legacy AI projects may contain an explicit recipe/VisualGraph whose
    # historical style record was never persisted. Preserve that recipe as the
    # migration authority. Every current preset transaction persists its base
    # record and therefore takes the canonical synchronization path below.
    if appearance_base_resolved:
        recipe = _materialize_recipe_appearance(
            recipe,
            style,
            resolved.appearance_override,
        )
    recipe = caption.recipe
    raw_fill = FillSpec.from_value(
        recipe.colors.get("fill", style.primary_color)
    ).to_dict()
    layers = recipe.outline.get("layers")
    if isinstance(layers, list) and layers:
        strokes = tuple(
            {
                **copy.deepcopy(dict(item)),
                "alignment": normalize_stroke_alignment(
                    item.get("alignment", recipe.outline.get("alignment"))
                ),
            }
            for item in layers if isinstance(item, Mapping)
        )
    else:
        strokes = ({"color": recipe.outline.get("color", style.outline_color),
                    "width": recipe.outline.get("width", style.outline_width),
                    "alignment": normalize_stroke_alignment(
                        recipe.outline.get("alignment")
                    )},)
    effects = recipe.effects if isinstance(recipe.effects, Mapping) else {}
    recipe_shadow = recipe.outline.get("shadow", style.shadow)
    shadow = normalize_shadow_contract(recipe_shadow)
    glow = normalize_glow_contract(effects.get("glow", {}))
    from .style_recipe import MOTION_SOURCE_NONE, motion_source

    raw_motion = recipe.motion if isinstance(recipe.motion, Mapping) else {}
    motion = normalize_motion_contract(raw_motion)
    graph_payload = recipe.visual_graph if isinstance(recipe.visual_graph, Mapping) else {}
    source = motion_source(motion, visual_graph=graph_payload)
    graph_motion = (
        copy.deepcopy(motion.get("graph"))
        if isinstance(motion.get("graph"), Mapping)
        else copy.deepcopy(graph_payload.get("motionGraph"))
        if isinstance(graph_payload.get("motionGraph"), Mapping)
        else {}
    )
    if motion_mode(motion) == MOTION_MODE_NONE and source == MOTION_SOURCE_NONE:
        motion_recipe = {
            "mode": MOTION_MODE_NONE,
            "origin": MOTION_SOURCE_NONE,
            "entrance": {}, "hold": {}, "exit": {},
        }
    elif source == "visual_graph" or graph_motion:
        motion_recipe = {
            "mode": motion_mode(motion) if motion_mode(motion) != MOTION_MODE_NONE else "explicit",
            "origin": "visual_graph",
            "graph": graph_motion,
            "entrance": copy.deepcopy(motion.get("entrance", motion.get("entry", {})) or {}),
            "hold": copy.deepcopy(motion.get("hold", {}) or {}),
            "exit": copy.deepcopy(motion.get("exit", {}) or {}),
        }
    elif any(key in motion for key in ("entrance", "hold", "exit")):
        motion_recipe = MotionRecipe(
            entrance=copy.deepcopy(motion.get("entrance", {})),
            hold=copy.deepcopy(motion.get("hold", {})),
            exit=copy.deepcopy(motion.get("exit", {})),
        ).to_dict()
        motion_recipe["mode"] = motion_mode(motion)
        motion_recipe["origin"] = source
    else:
        motion_recipe = {
            "mode": motion_mode(motion),
            "origin": source,
            "entrance": copy.deepcopy(motion.get("entry", {})),
            "hold": copy.deepcopy(motion.get("hold", {})),
            "exit": copy.deepcopy(motion.get("exit", {})),
        }
    position_x, position_y, anchor_x, anchor_y = _anchor(style, playres_x, playres_y)
    recipe.layout['positionY'] = position_y
    if recipe.web_theme:
        from .web_placement import cue_placement
        recipe.layout['webPlacement'] = cue_placement(project, cue)
    typography = recipe.typography if isinstance(recipe.typography, Mapping) else {}
    return VisualCueSnapshot(
        cue_id=cue.id, text=caption.text, start_ms=cue.start_ms, end_ms=cue.end_ms,
        font_family=style.font_family or str(typography.get("fontFamily") or "Microsoft YaHei UI"),
        font_size=float(style.font_size), font_weight=style.font_weight or (700 if style.bold else 400),
        italic=bool(style.italic), letter_spacing=float(style.spacing),
        fill=raw_fill, strokes=strokes,
        shadow=shadow,
        glow=glow,
        playres_x=playres_x, playres_y=playres_y,
        position_x=position_x, position_y=position_y, alignment=int(style.alignment),
        anchor_x=anchor_x, anchor_y=anchor_y,
        scale_x=float(style.scale_x) / 100.0, scale_y=float(style.scale_y) / 100.0,
        rotation=float(cue.transform.get("rotation", recipe.layout.get("rotation", 0)) or 0),
        style_recipe=recipe.to_dict(), motion_recipe=motion_recipe,
        speaker=cue.speaker_id, resolution=(output_width, output_height), fps=float(fps),
        appearance_generation=max(0, int(cue.appearance_generation)),
        project_id=str(project.project_id),
        translation=_cue_translation(project, cue.id),
        resolved_caption=caption,
    )
