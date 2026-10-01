"""Normalize semantic provider design responses into the graph contract.

Providers are allowed to describe intent (palette, layout, motion, effects)
without knowing the renderer's internal field names.  This module keeps that
translation deterministic and leaves graph validation to the existing V1
validator.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .studio_project import SubtitleStyle
from .style_recipe import StyleRecipe
from .visual_design_graph import VisualDesignGraph, graph_from_style_recipe


@dataclass(frozen=True)
class DesignProposalDTO:
    design_intent: str
    visual_changes: tuple[str, ...]
    motion_reason: str
    art_directions: tuple[Mapping[str, Any], ...]
    variants: tuple[VisualDesignGraph, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "design_intent": self.design_intent,
            "visual_changes": list(self.visual_changes),
            "motion_reason": self.motion_reason,
            "art_directions": [copy.deepcopy(dict(item)) for item in self.art_directions],
            "variants": [item.to_dict() for item in self.variants],
        }


def _first(value: Any, default: Any = None) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value[0] if value else default
    return value if value is not None else default


def _semantic_recipe(value: Mapping[str, Any], index: int) -> StyleRecipe:
    typography = value.get("typography") if isinstance(value.get("typography"), Mapping) else {}
    palette = value.get("palette") if isinstance(value.get("palette"), Mapping) else {}
    fill = value.get("fill", palette.get("fill", palette.get("primary", "#FFFFFFFF")))
    if isinstance(fill, Sequence) and not isinstance(fill, (str, bytes)):
        colors = [str(item) for item in fill if str(item).strip()]
        fill = colors[0] if len(colors) < 2 else {
            "type": "linear-gradient", "angle": 0,
            "stops": [{"position": i / (len(colors) - 1), "color": color} for i, color in enumerate(colors)],
        }
    elif isinstance(fill, Mapping):
        fill = copy.deepcopy(dict(fill))
        if "colors" in fill and "stops" not in fill:
            colors = [str(item) for item in fill.get("colors", ()) if str(item).strip()]
            fill = colors[0] if len(colors) < 2 else {
                "type": "linear-gradient", "angle": float(fill.get("angle", 0) or 0),
                "stops": [{"position": i / (len(colors) - 1), "color": color} for i, color in enumerate(colors)],
            }
    outline = value.get("outline", value.get("strokes", palette.get("outline", "#FF000000")))
    if isinstance(outline, Mapping):
        # StyleRecipe-shaped outline: use its layers (or flat color/width).
        layer_items = outline.get("layers")
        strokes = (
            [dict(item) for item in layer_items if isinstance(item, Mapping)]
            if isinstance(layer_items, list) else []
        )
        if not strokes and isinstance(outline.get("color"), str):
            strokes = [{
                "color": str(outline["color"]),
                "width": float(outline.get("width", 3) or 3),
            }]
    elif isinstance(outline, list):
        strokes = [dict(item) for item in outline if isinstance(item, Mapping)]
    else:
        strokes = []
    if not strokes:
        # Never stringify a non-color container into a stroke color.
        fallback_color = (
            outline
            if isinstance(outline, str) and outline.startswith("#")
            else "#FF000000"
        )
        strokes = [{"color": fallback_color, "width": float(value.get("outline_width", 3) or 3)}]
    layout = value.get("layout") if isinstance(value.get("layout"), Mapping) else {}
    panel = value.get("panel", value.get("background", {}))
    panel = dict(panel) if isinstance(panel, Mapping) else {}
    if "primitive" in panel and "type" not in panel:
        panel["type"] = str(panel.pop("primitive")).casefold()
    decorations = []
    for item in value.get("decorations", ()) if isinstance(value.get("decorations"), Sequence) else ():
        if isinstance(item, Mapping):
            decorations.append(dict(item))
        elif str(item).strip():
            decorations.append({"type": str(item).strip()})
    effects = value.get("effects") if isinstance(value.get("effects"), Mapping) else {}
    motion = value.get("motion") if isinstance(value.get("motion"), Mapping) else {}
    recipe = StyleRecipe(
        name=str(value.get("name") or value.get("concept") or f"AI 方案 {index + 1}"),
        engine="remotion",
        typography={
            "fontFamily": str(typography.get("fontFamily", typography.get("font_family", "Microsoft YaHei UI"))),
            "fontSize": float(typography.get("fontSize", typography.get("size", 52)) or 52),
            "bold": bool(typography.get("bold", int(typography.get("weight", 700) or 700) >= 700)),
            "italic": bool(typography.get("italic", False)),
            "spacing": float(typography.get("letterSpacing", typography.get("spacing", 0)) or 0),
        },
        layout={"alignment": int(layout.get("alignment", 2) or 2), "marginV": int(layout.get("marginV", 64) or 64), **dict(layout)},
        colors={"fill": fill, "outline": strokes[0].get("color", "#FF000000"), "background": panel.get("color", "#00000000")},
        outline={"layers": strokes, "color": strokes[0].get("color", "#FF000000"), "width": strokes[0].get("width", 3), "shadow": copy.deepcopy(value.get("shadow", {}))},
        background={"enabled": bool(panel.get("enabled", panel.get("type", "none") not in {"", "none"})), **panel},
        effects={"decorations": decorations, **dict(effects)},
        motion=dict(motion),
    )
    recipe.validate()
    return recipe


class ProviderOutputAdapter:
    """Accept graph-native or semantic provider output and return one DTO."""

    @staticmethod
    def _variant_rows(payload: Mapping[str, Any]) -> list[Any] | None:
        """Resolve the common semantic names providers use for A/B/C rows."""
        direct = payload.get("variants")
        if isinstance(direct, list):
            return direct
        for key in ("proposals", "designs", "directions"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
        return None

    @staticmethod
    def _unwrap_variant(item: Any) -> Any:
        if not isinstance(item, Mapping):
            return item
        # Providers often wrap a direction in a descriptive envelope. Keep
        # metadata at the row level but feed the actual semantic object to the
        # recipe compiler when one is present.
        for key in ("visualGraph", "visual_graph", "graph", "design", "proposal", "style", "recipe"):
            nested = item.get(key)
            if isinstance(nested, Mapping):
                return nested
        return item

    def adapt(self, payload: Mapping[str, Any], *, instruction: str = "") -> DesignProposalDTO:
        if not isinstance(payload, Mapping):
            raise ValueError("Provider output must be a JSON object")
        variants_payload = self._variant_rows(payload)
        if not isinstance(variants_payload, list) or len(variants_payload) != 3:
            raise ValueError("Provider output must contain exactly three variants/proposals/designs")
        graphs: list[VisualDesignGraph] = []
        for index, item in enumerate(variants_payload):
            item = self._unwrap_variant(item)
            if not isinstance(item, Mapping):
                raise ValueError(f"variant {index + 1} must be an object")
            graph_value = item.get("visualGraph", item.get("visual_graph"))
            if isinstance(graph_value, Mapping):
                item = graph_value
            if item.get("schema") == "2byte.visual-design-graph" or "textLayer" in item or "motionGraph" in item:
                graphs.append(VisualDesignGraph.from_dict(item))
            else:
                graphs.append(graph_from_style_recipe(_semantic_recipe(item, index)))
        directions = payload.get("art_directions")
        direction_rows = tuple(
            copy.deepcopy(dict(item)) for item in directions
            if isinstance(item, Mapping)
        ) if isinstance(directions, list) else ()
        return DesignProposalDTO(
            str(payload.get("design_intent") or payload.get("intent") or instruction or "").strip(),
            tuple(str(item) for item in payload.get("visual_changes", ()) if str(item).strip())
            if isinstance(payload.get("visual_changes"), list) else (),
            str(payload.get("motion_reason") or payload.get("motionReason") or "").strip(),
            direction_rows,
            tuple(graphs),
        )

    def adapt_payload(self, payload: Mapping[str, Any], *, instruction: str = "") -> dict[str, Any]:
        return self.adapt(payload, instruction=instruction).to_payload()


__all__ = ["DesignProposalDTO", "ProviderOutputAdapter"]
