"""Renderer capability and foreground ownership contracts for Studio preview."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from time import perf_counter_ns
from types import MappingProxyType
from typing import Any, Mapping


class VisualRenderer(str, Enum):
    NATIVE = "native"
    LIVE = "live"
    FIDELITY = "fidelity"
    EXPORT = "export"


class CapabilitySupport(IntEnum):
    NONE = 0
    APPROXIMATE = 1
    LIMITED = 2
    FULL = 3


class VisualCapability(str, Enum):
    SOLID_FILL = "solid_fill"
    GRADIENT_FILL = "gradient_fill"
    STROKE = "stroke"
    MULTI_STROKE = "multi_stroke"
    SHADOW = "shadow"
    GLOW = "glow"
    OPACITY = "opacity"
    BACKGROUND = "background"
    TRANSFORM = "transform"
    ALIGNMENT = "alignment"
    BASIC_MOTION = "basic_motion"
    COMPLEX_MOTION = "complex_motion"
    TEXTURE = "texture"
    MASK = "mask"
    DECORATION = "decoration"
    PANEL = "panel"
    COMIC_BURST = "comic_burst"
    GLITCH = "glitch"
    IMPACT = "impact"
    MOTION_GRAPH = "motion_graph"


_FULL = CapabilitySupport.FULL
_LIMITED = CapabilitySupport.LIMITED
_NONE = CapabilitySupport.NONE

VISUAL_CAPABILITY_MATRIX = MappingProxyType({
    VisualRenderer.NATIVE: MappingProxyType({
        VisualCapability.SOLID_FILL: _FULL,
        VisualCapability.GRADIENT_FILL: _NONE,
        VisualCapability.STROKE: _FULL,
        VisualCapability.MULTI_STROKE: _NONE,
        VisualCapability.SHADOW: _LIMITED,
        VisualCapability.GLOW: _NONE,
        VisualCapability.OPACITY: _FULL,
        VisualCapability.BACKGROUND: _LIMITED,
        VisualCapability.TRANSFORM: _FULL,
        VisualCapability.ALIGNMENT: _FULL,
        VisualCapability.BASIC_MOTION: _LIMITED,
        VisualCapability.COMPLEX_MOTION: _NONE,
        VisualCapability.TEXTURE: _NONE,
        VisualCapability.MASK: _NONE,
        VisualCapability.DECORATION: _NONE,
        VisualCapability.PANEL: _LIMITED,
        VisualCapability.COMIC_BURST: _NONE,
        VisualCapability.GLITCH: _NONE,
        VisualCapability.IMPACT: _NONE,
        VisualCapability.MOTION_GRAPH: _NONE,
    }),
    VisualRenderer.LIVE: MappingProxyType({
        VisualCapability.SOLID_FILL: _FULL,
        VisualCapability.GRADIENT_FILL: _FULL,
        VisualCapability.STROKE: _FULL,
        VisualCapability.MULTI_STROKE: _FULL,
        VisualCapability.SHADOW: _FULL,
        VisualCapability.GLOW: _FULL,
        VisualCapability.OPACITY: _FULL,
        VisualCapability.BACKGROUND: _FULL,
        VisualCapability.TRANSFORM: _FULL,
        VisualCapability.ALIGNMENT: _FULL,
        VisualCapability.BASIC_MOTION: _LIMITED,
        VisualCapability.COMPLEX_MOTION: _NONE,
        VisualCapability.TEXTURE: _NONE,
        VisualCapability.MASK: _NONE,
        VisualCapability.DECORATION: _FULL,
        VisualCapability.PANEL: _FULL,
        VisualCapability.COMIC_BURST: _FULL,
        VisualCapability.GLITCH: _FULL,
        VisualCapability.IMPACT: _FULL,
        VisualCapability.MOTION_GRAPH: _FULL,
    }),
    VisualRenderer.FIDELITY: MappingProxyType({
        VisualCapability.SOLID_FILL: _FULL,
        VisualCapability.GRADIENT_FILL: _FULL,
        VisualCapability.STROKE: _FULL,
        VisualCapability.MULTI_STROKE: _FULL,
        VisualCapability.SHADOW: _FULL,
        VisualCapability.GLOW: _FULL,
        VisualCapability.OPACITY: _FULL,
        VisualCapability.BACKGROUND: _FULL,
        VisualCapability.TRANSFORM: _FULL,
        VisualCapability.ALIGNMENT: _FULL,
        VisualCapability.BASIC_MOTION: _FULL,
        VisualCapability.COMPLEX_MOTION: _FULL,
        VisualCapability.TEXTURE: _FULL,
        VisualCapability.MASK: _LIMITED,
        VisualCapability.DECORATION: _FULL,
        VisualCapability.PANEL: _FULL,
        VisualCapability.COMIC_BURST: _FULL,
        VisualCapability.GLITCH: _FULL,
        VisualCapability.IMPACT: _FULL,
        VisualCapability.MOTION_GRAPH: _FULL,
    }),
    # Export consumes the same normalized TrustedSubtitle composition as the
    # Fidelity preview, so its contract is intentionally identical.
    VisualRenderer.EXPORT: MappingProxyType({
        VisualCapability.SOLID_FILL: _FULL,
        VisualCapability.GRADIENT_FILL: _FULL,
        VisualCapability.STROKE: _FULL,
        VisualCapability.MULTI_STROKE: _FULL,
        VisualCapability.SHADOW: _FULL,
        VisualCapability.GLOW: _FULL,
        VisualCapability.OPACITY: _FULL,
        VisualCapability.BACKGROUND: _FULL,
        VisualCapability.TRANSFORM: _FULL,
        VisualCapability.ALIGNMENT: _FULL,
        VisualCapability.BASIC_MOTION: _FULL,
        VisualCapability.COMPLEX_MOTION: _FULL,
        VisualCapability.TEXTURE: _FULL,
        VisualCapability.MASK: _LIMITED,
        VisualCapability.DECORATION: _FULL,
        VisualCapability.PANEL: _FULL,
        VisualCapability.COMIC_BURST: _FULL,
        VisualCapability.GLITCH: _FULL,
        VisualCapability.IMPACT: _FULL,
        VisualCapability.MOTION_GRAPH: _FULL,
    }),
})


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability: VisualCapability
    minimum: CapabilitySupport
    reason: str


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive(value: object) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _enabled_effect(value: object) -> bool:
    if isinstance(value, Mapping):
        if value.get("enabled") is False:
            return False
        return any(
            _positive(value.get(key))
            for key in (
                "strength", "opacity", "blur", "radius", "spread",
                "distance", "offset_x", "offsetX", "offset_y", "offsetY",
            )
        )
    return _positive(value)


def recipe_capability_requirements(
    recipe: Mapping[str, Any] | object,
) -> tuple[CapabilityRequirement, ...]:
    """Return the active visual requirements a renderer must not silently drop."""
    payload = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe
    root = _mapping(payload)
    colors = _mapping(root.get("colors"))
    visual_schema = any(
        key in root for key in ("engine_requirement", "fill", "strokes", "glow")
    )
    fill = _mapping(root.get("fill") if visual_schema else colors.get("fill"))
    outline = dict(_mapping(root.get("outline")))
    effects = dict(_mapping(root.get("effects")))
    if visual_schema:
        outline.setdefault("layers", root.get("strokes"))
        outline.setdefault("shadow", root.get("shadow"))
        effects.setdefault("glow", root.get("glow"))
        effects.setdefault("texture", root.get("texture"))
        effects.setdefault("mask", root.get("mask"))
        effects.setdefault("decorations", root.get("decorations"))
    background = _mapping(root.get("background"))
    motion = _mapping(root.get("motion"))
    requirements: dict[VisualCapability, CapabilityRequirement] = {}

    def require(
        capability: VisualCapability,
        minimum: CapabilitySupport,
        reason: str,
    ) -> None:
        current = requirements.get(capability)
        if current is None or minimum > current.minimum:
            requirements[capability] = CapabilityRequirement(capability, minimum, reason)

    fill_type = str(fill.get("type") or "solid").lower()
    if fill_type in {"linear", "linear-gradient", "radial", "radial-gradient"}:
        require(VisualCapability.GRADIENT_FILL, _FULL, "gradient fill")
    else:
        require(VisualCapability.SOLID_FILL, _FULL, "solid fill")

    layers = outline.get("layers")
    active_layers = [item for item in layers if isinstance(item, Mapping)] if isinstance(layers, list) else []
    if len(active_layers) > 1:
        require(VisualCapability.MULTI_STROKE, _FULL, "multiple stroke layers")
    elif active_layers or _positive(outline.get("width")):
        require(VisualCapability.STROKE, _FULL, "glyph stroke")

    shadow = outline.get("shadow", effects.get("shadow"))
    if _enabled_effect(shadow):
        # The Studio slider compiles blur/opacity/offset semantics. Native ASS
        # distance alone is only LIMITED and cannot satisfy that contract.
        require(VisualCapability.SHADOW, _FULL, "canonical soft glyph shadow")

    glow = effects.get("glow")
    if _enabled_effect(glow):
        require(VisualCapability.GLOW, _FULL, "glyph glow")

    if bool(background.get("enabled", False)):
        advanced_background = set(background) - {"enabled", "color"}
        require(
            VisualCapability.BACKGROUND,
            _FULL if advanced_background else _LIMITED,
            "composited background" if advanced_background else "simple background",
        )

    layout = _mapping(root.get("layout"))
    if any(key in layout for key in ("positionX", "positionY", "scaleX", "scaleY", "rotation")):
        require(VisualCapability.TRANSFORM, _FULL, "subtitle transform")
    require(VisualCapability.ALIGNMENT, _FULL, "subtitle alignment")

    motion_types: list[str] = []
    for name in ("entrance", "entry", "hold", "exit"):
        part = motion.get(name)
        if isinstance(part, Mapping):
            motion_types.append(str(part.get("type") or "none").lower())
        elif part:
            motion_types.append(str(part).lower())
    motion_types = [item for item in motion_types if item not in {"", "none"}]
    if motion_types:
        basic = {"fade", "slide", "scale", "fade_in", "fade_out"}
        require(
            VisualCapability.BASIC_MOTION if all(item in basic for item in motion_types) else VisualCapability.COMPLEX_MOTION,
            _LIMITED if all(item in basic for item in motion_types) else _FULL,
            "basic motion" if all(item in basic for item in motion_types) else "complex motion",
        )

    if _mapping(effects.get("texture")):
        require(VisualCapability.TEXTURE, _FULL, "texture")
    if _mapping(effects.get("mask")):
        require(VisualCapability.MASK, _FULL, "mask")
    decorations = effects.get("decorations") or background.get("marks")
    if decorations:
        require(VisualCapability.DECORATION, _FULL, "decorations")

    graph_payload = root.get("visualGraph")
    if isinstance(graph_payload, Mapping) and graph_payload:
        from .visual_design_graph import VisualDesignGraph

        graph = VisualDesignGraph.from_dict(graph_payload)
        if graph.panel_layer.primitive != "NONE":
            require(VisualCapability.PANEL, _FULL, "layered panel")
        if graph.panel_layer.primitive == "COMIC_BURST":
            require(VisualCapability.COMIC_BURST, _FULL, "comic burst panel")
        if graph.decoration_layers:
            require(VisualCapability.DECORATION, _FULL, "layered decorations")
        for effect_layer in graph.effect_layers:
            if effect_layer.primitive == "GLITCH":
                require(VisualCapability.GLITCH, _FULL, "deterministic glitch effect")
            elif effect_layer.primitive == "IMPACT":
                require(VisualCapability.IMPACT, _FULL, "impact effect")
        if graph.motion_graph.tracks:
            require(VisualCapability.MOTION_GRAPH, _FULL, "layer motion graph")

    return tuple(requirements[capability] for capability in VisualCapability if capability in requirements)


def renderer_capability_gaps(
    renderer: VisualRenderer,
    recipe: Mapping[str, Any] | object,
) -> tuple[CapabilityRequirement, ...]:
    support = VISUAL_CAPABILITY_MATRIX[VisualRenderer(renderer)]
    return tuple(
        requirement
        for requirement in recipe_capability_requirements(recipe)
        if support.get(requirement.capability, _NONE) < requirement.minimum
    )


class VisualOwner(str, Enum):
    NONE = "none"
    NATIVE = "native"
    ADVANCED_LIVE = "advanced_live"
    ADVANCED_FIDELITY = "advanced_fidelity"


@dataclass(frozen=True, slots=True)
class VisualOwnership:
    owner: VisualOwner = VisualOwner.NONE
    cue_id: str = ""
    snapshot_hash: str = ""
    request_key: str = ""
    revision: int = 0
    committed_ns: int = 0

    @property
    def foreground_owner_count(self) -> int:
        return 0 if self.owner == VisualOwner.NONE else 1


class VisualOwnershipStateMachine:
    """One authoritative foreground owner; transport mirrors are not owners."""

    def __init__(self) -> None:
        self.current = VisualOwnership()

    def commit(
        self,
        owner: VisualOwner,
        *,
        cue_id: str = "",
        snapshot_hash: str = "",
        request_key: str = "",
    ) -> tuple[VisualOwnership, VisualOwnership]:
        owner = VisualOwner(owner)
        cue_id = str(cue_id or "")
        if owner == VisualOwner.NONE:
            cue_id = snapshot_hash = request_key = ""
        elif not cue_id:
            raise ValueError("a foreground owner requires a cue id")
        previous = self.current
        candidate = VisualOwnership(
            owner=owner,
            cue_id=cue_id,
            snapshot_hash=str(snapshot_hash or ""),
            request_key=str(request_key or ""),
            revision=previous.revision + 1,
            committed_ns=perf_counter_ns(),
        )
        if (
            previous.owner,
            previous.cue_id,
            previous.snapshot_hash,
            previous.request_key,
        ) == (
            candidate.owner,
            candidate.cue_id,
            candidate.snapshot_hash,
            candidate.request_key,
        ):
            return previous, previous
        self.current = candidate
        return previous, candidate


__all__ = [
    "CapabilityRequirement",
    "CapabilitySupport",
    "VISUAL_CAPABILITY_MATRIX",
    "VisualCapability",
    "VisualOwner",
    "VisualOwnership",
    "VisualOwnershipStateMachine",
    "VisualRenderer",
    "recipe_capability_requirements",
    "renderer_capability_gaps",
]
