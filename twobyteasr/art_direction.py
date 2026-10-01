"""Semantic art direction and local quality policy for Creative Engine V2.

ArtDirectionSpec deliberately contains design decisions, not renderer values.
Trusted planners compile it into VisualDesignGraph; LIVE and Remotion then
compile that graph without asking the model to emit executable code.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from .visual_design_graph import (
    DecorationLayer,
    EffectLayer,
    MotionKeyframe,
    MotionTrack,
    VisualDesignGraph,
    is_weak_motion_graph,
    readability_issues,
    repair_weak_motion_graph,
    visual_composition_bounds,
)


ART_DIRECTION_SCHEMA = "2byte.art-direction-spec"
ART_DIRECTION_VERSION = 1


class DecorationDensity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class ArtDirectionSpec:
    concept_name: str
    intent: str
    emotion: str
    visual_language: str
    reference_family: str
    hierarchy: str
    text_emphasis: str
    composition: str
    shape_language: str
    color_strategy: str
    contrast_strategy: str
    motion_concept: str
    entrance_feel: str
    hold_feel: str
    exit_feel: str
    decoration_strategy: str
    effect_strategy: str
    density: DecorationDensity = DecorationDensity.MEDIUM
    energy: str = "CONTROLLED"
    readability: str = "PRIMARY"
    avoid: tuple[str, ...] = ()
    primary_family: str = "CLEAN_EDITORIAL"
    secondary_family: str = ""
    family_mix: tuple[int, int] = (100, 0)
    regeneration_anchor: str = ""
    schema: str = ART_DIRECTION_SCHEMA
    version: int = ART_DIRECTION_VERSION

    def validate(self) -> "ArtDirectionSpec":
        if self.schema != ART_DIRECTION_SCHEMA or self.version != ART_DIRECTION_VERSION:
            raise ValueError("unsupported ArtDirectionSpec schema/version")
        for name in (
            "concept_name", "intent", "emotion", "visual_language",
            "reference_family", "hierarchy", "text_emphasis", "composition",
            "shape_language", "color_strategy", "contrast_strategy",
            "motion_concept", "entrance_feel", "hold_feel", "exit_feel",
            "decoration_strategy", "effect_strategy", "energy", "readability",
            "primary_family",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value or len(value) > 500:
                raise ValueError(f"ArtDirectionSpec.{name} is required and must be concise")
        if self.primary_family not in ART_DIRECTION_TEMPLATES:
            raise ValueError(f"unknown primary family: {self.primary_family}")
        if self.secondary_family and self.secondary_family not in ART_DIRECTION_TEMPLATES:
            raise ValueError(f"unknown secondary family: {self.secondary_family}")
        primary, secondary = (int(self.family_mix[0]), int(self.family_mix[1]))
        if primary + secondary != 100 or primary < 60 or secondary < 0:
            raise ValueError("family_mix must preserve one dominant direction")
        if not 1 <= len(self.avoid) <= 16:
            raise ValueError("ArtDirectionSpec.avoid requires 1-16 constraints")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["density"] = self.density.value
        payload["avoid"] = list(self.avoid)
        payload["family_mix"] = list(self.family_mix)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtDirectionSpec":
        if not isinstance(payload, Mapping):
            raise ValueError("ArtDirectionSpec must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"ArtDirectionSpec has unknown fields: {sorted(unknown)}")
        values = copy.deepcopy(dict(payload))
        values["density"] = DecorationDensity(str(values.get("density") or "MEDIUM").upper())
        values["avoid"] = tuple(str(item) for item in values.get("avoid") or ())
        values["family_mix"] = tuple(int(item) for item in values.get("family_mix") or (100, 0))
        return cls(**values).validate()


@dataclass(frozen=True)
class ArtDirectionTemplate:
    family_id: str
    display_name: str
    allowed_layers: tuple[str, ...]
    recommended_composition: str
    motion_vocabulary: tuple[str, ...]
    easing: tuple[str, ...]
    density_range: tuple[DecorationDensity, ...]
    color_constraints: str
    readability_rules: str
    forbidden_cheap_patterns: tuple[str, ...]
    fill_strategies: tuple[str, ...] = ("solid",)
    panel_vocabulary: tuple[str, ...] = ("NONE",)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "display_name": self.display_name,
            "allowed_layers": list(self.allowed_layers),
            "recommended_composition": self.recommended_composition,
            "motion_vocabulary": list(self.motion_vocabulary),
            "easing": list(self.easing),
            "density_range": [item.value for item in self.density_range],
            "color_constraints": self.color_constraints,
            "readability_rules": self.readability_rules,
            "forbidden_cheap_patterns": list(self.forbidden_cheap_patterns),
            "fill_strategies": list(self.fill_strategies),
            "panel_vocabulary": list(self.panel_vocabulary),
        }


def _template(
    family_id: str,
    display_name: str,
    layers: tuple[str, ...],
    composition: str,
    motion: tuple[str, ...],
    colors: str,
    readability: str,
    *,
    density: tuple[DecorationDensity, ...] = (DecorationDensity.LOW, DecorationDensity.MEDIUM),
    forbidden: tuple[str, ...] = ("uniform linear scale", "all layers move together", "continuous flicker"),
    fills: tuple[str, ...] = ("solid",),
    panels: tuple[str, ...] = ("NONE",),
) -> ArtDirectionTemplate:
    return ArtDirectionTemplate(
        family_id, display_name, layers, composition, motion,
        ("spring", "damped-spring", "impact", "ease-out-expo", "ease-out-back"),
        density, colors, readability, forbidden, fills, panels,
    )


ART_DIRECTION_TEMPLATES: dict[str, ArtDirectionTemplate] = {
    item.family_id: item for item in (
        _template("AMERICAN_COMIC_BURST", "American Comic Burst", ("COMIC_BURST", "COMIC_BUBBLE", "IMPACT_RAYS", "HALFTONE", "IMPACT", "ARROWS", "TORN_PAPER"), "Text center; burst behind; rays outside; small halftone accents", ("panel expansion", "rays stagger", "text impact", "damped settle"), "One paper/light fill, one ink outline, one semantic accent", "Text > burst > rays > halftone", density=(DecorationDensity.MEDIUM, DecorationDensity.HIGH), fills=("solid", "two-tone", "highlight-gradient"), panels=("COMIC_BURST", "COMIC_BUBBLE", "TORN_PAPER")),
        _template("MANGA_IMPACT", "Manga Impact", ("COMIC_BURST", "ANGLED_PLATE", "SPEED_LINES", "SHARDS", "IMPACT", "ARROWS", "TORN_PAPER"), "Strong text axis with directional speed lines and bounded shards", ("anticipation", "directional strike", "text impact", "short settle"), "Ink-led grayscale or restrained two-color manga palette", "Text remains the darkest or lightest visual mass", fills=("solid", "two-tone"), panels=("COMIC_BURST", "ANGLED_PLATE", "TORN_PAPER")),
        _template("HALFTONE_SLAM", "Halftone Slam", ("CUT_CORNER", "UNDERLINE_SLAB", "HALFTONE", "IMPACT"), "Compact cut plate with halftone limited to corners or edge bands", ("panel snap", "dot reveal", "text slam", "stable hold"), "Two inks plus one warm accent; dots never reduce glyph contrast", "Halftone stays secondary and outside glyph interiors", fills=("solid", "highlight-gradient"), panels=("CUT_CORNER", "UNDERLINE_SLAB")),
        _template("SPEEDLINE_PUNCH", "Speedline Punch", ("NONE", "SPEED_LINES", "IMPACT", "ARROWS"), "Open composition with speed lines aimed toward the text", ("pre-pull", "fast strike", "line stagger", "impact settle"), "High contrast text; lines use one subordinate accent", "Lines frame the text and never cross its readable core"),
        _template("CRT_GLITCH", "CRT Glitch", ("RECTANGLE", "CUT_CORNER", "SCANLINES", "GLITCH", "SCAN_SWEEP"), "Horizontal slices and local scanlines around a stable text lockup", ("pre-glitch", "signal break", "fast lock", "stable hold", "optional micro break"), "Use video-aware light/dark base; RGB split is brief and local", "Glitch recovers by 320ms and the hold is stable", fills=("solid", "cyan-blue-gradient", "cyan-magenta-gradient"), panels=("CUT_CORNER", "RECTANGLE")),
        _template("SIGNAL_LOSS", "Signal Loss", ("RECTANGLE", "SCANLINES", "ACCENT_BARS", "GLITCH", "SCAN_SWEEP", "DATA_BARS"), "Narrow signal window with sparse telemetry accents", ("dropout", "reacquire", "lock", "quiet hold"), "Desaturated signal base plus one alert accent", "Never hide the full line during hold"),
        _template("CYBER_HUD", "Cyber HUD", ("TECH_FRAME", "BRACKET_FRAME", "ACCENT_BARS", "SCANLINES", "SCAN_SWEEP", "DATA_BARS", "PARTICLES", "CROSSHAIR", "GLASS_PANEL"), "Bounded asymmetric HUD frame with offset metadata accents", ("line draw", "data tick", "text lock", "steady hold"), "Derive accent from frame palette; do not default to cyan-magenta", "HUD mass stays below text mass", fills=("solid", "cyan-blue-gradient", "controlled-neon-gradient"), panels=("TECH_FRAME", "BRACKET_FRAME", "GLASS_PANEL")),
        _template("DATA_SCAN", "Data Scan", ("NONE", "UNDERLINE_SLAB", "SCANLINES", "ACCENT_BARS", "SCAN_SWEEP", "DATA_BARS"), "Clean text with one scanning accent and offset underline slab", ("scan reveal", "quick resolve", "readable hold", "clean exit"), "Neutral text plus one sampled accent", "Scanline never continuously crosses the glyphs", fills=("solid", "cyan-blue-gradient"), panels=("NONE", "UNDERLINE_SLAB")),
        _template("CRITICAL_HIT", "Critical Hit", ("BADGE", "IMPACT_RAYS", "SHARDS", "IMPACT"), "Compact score badge behind a large punchline", ("anticipation squash", "critical strike", "shard stagger", "spring settle"), "High-value warm accent against dark outline; max three colors", "Text and number dominate badge and shards"),
        _template("ACHIEVEMENT_POP", "Achievement Pop", ("BADGE", "ACCENT_BARS", "IMPACT"), "Badge or ribbon anchored close to the subtitle text", ("badge unfold", "text pop", "accent tick", "calm hold"), "Positive semantic accent chosen against video luminance", "Badge supports text and stays within normal overflow"),
        _template("STREAMER_EMPHASIS", "Streamer Emphasis", ("RIBBON", "ACCENT_BARS", "SPEED_LINES", "IMPACT", "PARTICLES", "PILL"), "Broadcast-safe ribbon with restrained directional accents", ("directional entrance", "impact", "accent stagger", "stable hold"), "Match channel/video palette; avoid automatic neon pairs", "Readable first, expressive second", panels=("RIBBON", "PILL")),
        _template("KILL_FEED", "Kill Feed", ("ROUNDED_PANEL", "ACCENT_BARS", "DATA_BARS", "PILL"), "Compact horizontal information strip with clear text hierarchy", ("fast acquire", "short tick", "steady hold", "quick clear"), "Team/semantic accent plus neutral panel", "Dense information remains scannable", panels=("ROUNDED_PANEL", "PILL")),
        _template("CLEAN_EDITORIAL", "Clean Editorial", ("NONE", "ACCENT_BARS", "GLASS_PANEL"), "Typography-led layout with one optional editorial rule", ("soft anticipation", "precise reveal", "still hold", "quiet exit"), "Video-aware neutral pair and one reserved accent", "Text is the entire primary mass", density=(DecorationDensity.LOW,), panels=("NONE", "GLASS_PANEL")),
        _template("INDUSTRIAL_BRASS_HUD", "Industrial Brass HUD", ("MECHANICAL_PLATE", "RIVETS", "GAUGE", "PIPES", "GEARS"), "Iron plate with brass instruments; riveted frame and pressure gauge accents", ("plate draw-on", "gauge needle sweep", "rivet pop", "text mask reveal", "stable hold"), "Warm brass/copper metallics over dark iron; never neon cyan", "Text gradient stays brighter than the plate", fills=("metallic-gradient", "brass-gradient", "copper-gradient"), panels=("MECHANICAL_PLATE",)),
        _template("VICTORIAN_MECHANICAL", "Victorian Mechanical Plate", ("MECHANICAL_PLATE", "GEARS", "STEAM", "RIVETS"), "Ornate engraved plate flanked by turning gears with drifting steam", ("plate settle", "gears turn", "steam drift", "glyph reveal", "calm hold"), "Aged copper and parchment tones with deep sepia outline", "Serif-leaning glyphs dominate the plate", fills=("copper-gradient", "parchment-gradient"), panels=("MECHANICAL_PLATE",)),
        _template("STEAM_GAUGE_TYPO", "Steam Gauge Typography", ("LOWER_THIRD", "GAUGE", "RIVETS", "STEAM", "PIPES"), "Typography locked inside a steam-pressure dial over a lower-third slab", ("needle sweep", "dial settle", "text reveal", "vapor drift"), "Aged gold dial markings, needle as the only bright accent", "Needle never crosses glyph interiors during hold", fills=("aged-gold-gradient",), panels=("LOWER_THIRD",)),
    )
}


_FAMILY_SIGNATURES: dict[str, tuple[frozenset[str], ...]] = {
    "AMERICAN_COMIC_BURST": (frozenset({"COMIC_BURST"}), frozenset({"IMPACT_RAYS"}), frozenset({"IMPACT"})),
    "MANGA_IMPACT": (frozenset({"SPEED_LINES", "SHARDS"}), frozenset({"IMPACT"})),
    "HALFTONE_SLAM": (frozenset({"CUT_CORNER", "UNDERLINE_SLAB"}), frozenset({"HALFTONE"})),
    "SPEEDLINE_PUNCH": (frozenset({"SPEED_LINES"}), frozenset({"IMPACT"})),
    "CRT_GLITCH": (frozenset({"GLITCH"}), frozenset({"SCANLINES"})),
    "SIGNAL_LOSS": (frozenset({"GLITCH"}), frozenset({"SCANLINES", "ACCENT_BARS"})),
    "CYBER_HUD": (frozenset({"TECH_FRAME", "BRACKET_FRAME"}), frozenset({"ACCENT_BARS", "SCANLINES"})),
    "DATA_SCAN": (frozenset({"SCANLINES", "ACCENT_BARS"}),),
    "CRITICAL_HIT": (frozenset({"BADGE"}), frozenset({"IMPACT"})),
    "ACHIEVEMENT_POP": (frozenset({"BADGE"}), frozenset({"ACCENT_BARS"})),
    "STREAMER_EMPHASIS": (frozenset({"RIBBON"}), frozenset({"ACCENT_BARS", "SPEED_LINES"})),
    "KILL_FEED": (frozenset({"ROUNDED_PANEL"}), frozenset({"ACCENT_BARS"})),
    "CLEAN_EDITORIAL": (),
    "INDUSTRIAL_BRASS_HUD": (
        frozenset({"MECHANICAL_PLATE"}),
        frozenset({"RIVETS", "GAUGE", "PIPES"}),
    ),
    "VICTORIAN_MECHANICAL": (
        frozenset({"MECHANICAL_PLATE"}),
        frozenset({"GEARS"}),
    ),
    "STEAM_GAUGE_TYPO": (
        frozenset({"GAUGE"}),
        frozenset({"LOWER_THIRD"}),
    ),
}


def validate_graph_for_direction(
    graph: VisualDesignGraph,
    direction: ArtDirectionSpec,
) -> None:
    """Require one graph to implement its own declared art direction."""

    graph.validate()
    direction.validate()
    family_ids = tuple(
        item for item in (direction.primary_family, direction.secondary_family)
        if item in ART_DIRECTION_TEMPLATES
    )
    allowed = {"NONE"}
    for family_id in family_ids:
        allowed.update(ART_DIRECTION_TEMPLATES[family_id].allowed_layers)
    used = {
        graph.panel_layer.primitive,
        *(item.primitive for item in graph.decoration_layers),
        *(item.primitive for item in graph.effect_layers),
    }
    unsupported = used - allowed
    if unsupported:
        raise ValueError(
            f"{direction.primary_family} graph uses forbidden primitives: {sorted(unsupported)}"
        )
    for alternatives in _FAMILY_SIGNATURES.get(direction.primary_family, ()):
        if not used.intersection(alternatives):
            raise ValueError(
                f"{direction.primary_family} graph is missing one of {sorted(alternatives)}"
            )
    if direction.primary_family != "CLEAN_EDITORIAL" and not graph.motion_graph.tracks:
        raise ValueError(f"{direction.primary_family} graph requires family motion")
    motion_concept = str(direction.motion_concept or "").casefold()
    if motion_concept and motion_concept not in {"none", "static", "静态", "静态设计"}:
        if not graph.motion_graph.tracks:
            raise ValueError("ART_DIRECTION_MISMATCH: motion concept has no MotionGraph tracks")
    effect_concept = str(direction.effect_strategy or "").casefold()
    if "GLITCH" in allowed and (
        direction.primary_family in {"CRT_GLITCH", "SIGNAL_LOSS"} or any(
            token in f"{effect_concept} {motion_concept}"
            for token in ("glitch", "故障")
        )
    ):
        if not any(item.primitive == "GLITCH" for item in graph.effect_layers):
            raise ValueError("ART_DIRECTION_MISMATCH: declared glitch effect is absent")
        if not any(
            track.target in {item.id for item in graph.effect_layers if item.primitive == "GLITCH"}
            for track in graph.motion_graph.tracks
        ):
            raise ValueError("ART_DIRECTION_MISMATCH: glitch effect is static")
    semantic_motion = f"{direction.motion_concept} {direction.decoration_strategy}".casefold()
    # Token checks below turn prose mentions into structural declarations, but
    # only when the declared families can actually express the primitive.
    # Rhetoric such as "relying on motion for impact" under CLEAN_EDITORIAL
    # must not demand a layer the family vocabulary forbids.
    if (
        any(token in semantic_motion for token in ("scan", "扫描"))
        and allowed.intersection({"SCANLINES", "GLITCH"})
    ):
        scan_ids = {
            item.id for item in (*graph.decoration_layers, *graph.effect_layers)
            if item.primitive in {"SCANLINES", "GLITCH"}
        }
        if not scan_ids or not any(
            track.target in scan_ids for track in graph.motion_graph.tracks
        ):
            raise ValueError("ART_DIRECTION_MISMATCH: declared scan movement is absent or static")
    declared_motion = f"{effect_concept} {semantic_motion}"
    if (
        any(token in declared_motion for token in ("impact", "冲击"))
        and allowed.intersection({"IMPACT", "IMPACT_RAYS"})
    ):
        impact_ids = {
            item.id for item in (*graph.decoration_layers, *graph.effect_layers)
            if item.primitive in {"IMPACT", "IMPACT_RAYS"}
        }
        if not impact_ids or not any(
            track.target in impact_ids for track in graph.motion_graph.tracks
        ):
            raise ValueError("ART_DIRECTION_MISMATCH: impact effect is absent or static")
    if (
        any(token in declared_motion for token in ("shard", "碎片"))
        and "SHARDS" in allowed
    ):
        shard_ids = {
            item.id for item in (*graph.decoration_layers, *graph.effect_layers)
            if item.primitive == "SHARDS"
        }
        if not shard_ids or not any(
            track.target in shard_ids for track in graph.motion_graph.tracks
        ):
            raise ValueError("ART_DIRECTION_MISMATCH: shard effect is absent or static")


def art_direction_mismatches(
    graph: VisualDesignGraph,
    direction: ArtDirectionSpec,
) -> tuple[str, ...]:
    """Return deterministic semantic/graph contract failures."""

    try:
        validate_graph_for_direction(graph, direction)
    except ValueError as exc:
        message = str(exc)
        if "ART_DIRECTION_MISMATCH" in message or "requires family motion" in message:
            return ("ART_DIRECTION_MISMATCH",)
    return ()


# ---------------------------------------------------------------------------
# User ArtDirection → VisualDesignGraph fidelity contract.
#
# Natural-language descriptions must not become "fake design". Two gates:
# 1. Per-graph: every visual idea the USER explicitly typed (齿轮, 多层描边,
#    金属感, 色散, ...) must materialize in that graph as a real primitive or
#    typography feature.
# 2. Triple-level: when the instruction names a style family (蒸汽朋克/
#    steampunk, 赛博/cyber, ...), all three variants must stay inside that
#    direction as materially different sub-styles — never unrelated families —
#    and the triple must carry the direction's signature primitives and
#    palette evidence.
# ---------------------------------------------------------------------------

_INTENT_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "steampunk": {
        "tokens": (
            "蒸汽朋克", "steampunk", "维多利亚", "victorian", "黄铜", "brass",
            "齿轮", "gear", "cog",
        ),
        "families": {"INDUSTRIAL_BRASS_HUD", "VICTORIAN_MECHANICAL", "STEAM_GAUGE_TYPO"},
        "primitives": {"GEARS", "RIVETS", "GAUGE", "PIPES", "STEAM", "MECHANICAL_PLATE"},
        "min_graphs_with_primitives": 2,
        "min_graphs_warm_metallic": 2,
    },
    "cyber": {
        "tokens": ("赛博", "cyber", "霓虹", "neon", "hud"),
        "families": {"CRT_GLITCH", "SIGNAL_LOSS", "CYBER_HUD", "DATA_SCAN"},
        "primitives": {
            "TECH_FRAME", "BRACKET_FRAME", "SCANLINES", "GLITCH", "SCAN_SWEEP",
            "DATA_BARS", "CROSSHAIR", "PIXEL_TILES",
        },
        "min_graphs_with_primitives": 2,
    },
    "comic": {
        "tokens": ("美漫", "漫画", "comic", "manga", "爆裂", "burst"),
        "families": {"AMERICAN_COMIC_BURST", "MANGA_IMPACT", "HALFTONE_SLAM", "SPEEDLINE_PUNCH"},
        "primitives": {
            "COMIC_BURST", "COMIC_BUBBLE", "SPEED_LINES", "HALFTONE", "INK_SPLAT",
            "TORN_PAPER",
        },
        "min_graphs_with_primitives": 2,
    },
    "glitch": {
        "tokens": ("故障", "glitch"),
        "families": {"CRT_GLITCH", "SIGNAL_LOSS"},
        "primitives": {"GLITCH", "SCANLINES", "SCAN_SWEEP"},
        "min_graphs_with_primitives": 2,
    },
    "gaming": {
        "tokens": ("游戏", "直播", "gaming", "主播", "streamer", "achievement"),
        "families": {
            "CRITICAL_HIT", "STREAMER_EMPHASIS", "ACHIEVEMENT_POP", "KILL_FEED",
        },
        "primitives": {"BADGE", "RIBBON", "IMPACT", "IMPACT_RAYS", "ACCENT_BARS", "PILL"},
        "min_graphs_with_primitives": 2,
    },
}

# User-typed token → primitive the graph must then contain.
_PROSE_PRIMITIVE_CLAIMS: dict[str, tuple[str, ...]] = {
    "GEARS": ("gear", "齿轮", "cog"),
    "RIVETS": ("rivet", "铆钉"),
    "GAUGE": ("gauge", "仪表盘", "表盘"),
    "PIPES": ("pipe", "管道"),
    "STEAM": ("steam", "烟雾", "vapor"),
    "SCANLINES": ("scanline", "扫描线"),
    "SPEED_LINES": ("speed line", "速度线"),
    "HALFTONE": ("halftone", "网点"),
    "SHARDS": ("shard", "碎片"),
    "IMPACT_RAYS": ("impact ray", "放射线"),
    "ARROWS": ("arrow", "箭头"),
    "DATA_BARS": ("data bar", "数据条"),
    "PARTICLES": ("particle", "粒子"),
}


def _token_present(text: str, token: str) -> bool:
    """Substring for CJK, word-boundary (with plural) for ASCII tokens."""
    if token.isascii():
        return re.search(rf"\b{re.escape(token)}(?:s|es)?\b", text) is not None
    return token in text

_METALLIC_TOKENS = ("metallic", "金属", "brass", "黄铜", "copper", "铜", "gold", "金色", "铬", "chrome")
_GRADIENT_TOKENS = ("gradient", "渐变")
_MULTI_STROKE_TOKENS = ("multi-layer outline", "multilayer outline", "多层描边", "双描边", "stacked stroke", "multi-stroke")
_GLOW_TOKENS = ("glow", "辉光", "发光")
_SHADOW_TOKENS = ("shadow", "阴影", "投影")
_RGB_SPLIT_TOKENS = ("rgb split", "色散")


def _warm_metallic_evidence(graph: VisualDesignGraph) -> bool:
    """True when the TEXT layer itself carries a warm brass/copper/gold finish."""
    from PySide6.QtGui import QColor

    def colors() -> list[str]:
        result: list[str] = []
        fill = graph.text_layer.fill
        if isinstance(fill, str):
            result.append(fill)
        elif isinstance(fill, Mapping):
            color = str(fill.get("color") or "").strip()
            if color:
                result.append(color)
            for stop in fill.get("stops", ()) or ():
                if isinstance(stop, Mapping) and str(stop.get("color") or "").strip():
                    result.append(str(stop["color"]))
        for stroke in graph.text_layer.strokes:
            color = str(stroke.get("color") or "").strip()
            if color:
                result.append(color)
        return result

    for value in colors():
        color = QColor(value) if len(value) in {7, 9} else QColor()
        if not color.isValid():
            continue
        hue, saturation, lightness = color.hslHue(), color.hslSaturation(), color.lightness()
        if 15 <= hue <= 60 and saturation >= 48 and lightness >= 70:
            return True
    fill = graph.text_layer.fill
    return isinstance(fill, Mapping) and len(fill.get("stops") or ()) >= 2


def validate_graph_matches_instruction(
    instruction: str,
    direction: ArtDirectionSpec,
    graph: VisualDesignGraph,
) -> None:
    """Every visual idea the USER typed must materialize in this graph.

    A beautiful description over a white-text single-stroke graph is fake
    design. Raises ``ValueError`` starting with ``ART_DIRECTION_MISMATCH``
    when explicit user words have no structural counterpart.
    """
    instruction_text = str(instruction or "").casefold()
    used = {
        graph.panel_layer.primitive,
        *(item.primitive for item in graph.decoration_layers),
        *(item.primitive for item in graph.effect_layers),
    }
    for primitive, tokens in _PROSE_PRIMITIVE_CLAIMS.items():
        if any(_token_present(instruction_text, token) for token in tokens) and primitive not in used:
            raise ValueError(
                f"ART_DIRECTION_MISMATCH: instruction asks for {primitive} but the graph omits it"
            )
    fill = graph.text_layer.fill
    stops = fill.get("stops") or () if isinstance(fill, Mapping) else ()
    if any(_token_present(instruction_text, token) for token in _GRADIENT_TOKENS) and len(stops) < 2:
        raise ValueError("ART_DIRECTION_MISMATCH: requested gradient fill has no stops")
    if (
        any(_token_present(instruction_text, token) for token in _METALLIC_TOKENS)
        and len(stops) < 2
        and not _warm_metallic_evidence(graph)
    ):
        raise ValueError(
            "ART_DIRECTION_MISMATCH: requested metallic finish needs a multi-stop "
            "metallic gradient fill or warm metallic stroke"
        )
    if (
        any(_token_present(instruction_text, token) for token in _MULTI_STROKE_TOKENS)
        and len(graph.text_layer.strokes) < 2
    ):
        raise ValueError("ART_DIRECTION_MISMATCH: requested multi-layer outline has fewer than 2 strokes")
    if any(_token_present(instruction_text, token) for token in _GLOW_TOKENS) and not _glow_enabled(graph):
        raise ValueError("ART_DIRECTION_MISMATCH: requested glow is absent")
    if any(_token_present(instruction_text, token) for token in _SHADOW_TOKENS) and not _shadow_enabled(graph):
        raise ValueError("ART_DIRECTION_MISMATCH: requested drop shadow is absent")
    if (
        any(_token_present(instruction_text, token) for token in _RGB_SPLIT_TOKENS)
        and not any(item.primitive == "RGB_SPLIT" for item in graph.effect_layers)
    ):
        raise ValueError("ART_DIRECTION_MISMATCH: requested RGB split effect is absent")


def validate_variants_match_instruction(
    instruction: str,
    directions: tuple[ArtDirectionSpec, ...] | list[ArtDirectionSpec],
    graphs: list[VisualDesignGraph],
) -> None:
    """The whole A/B/C triple must stay inside the user's named direction.

    蒸汽朋克 in, Clean Editorial / Manga / Cyber out: all three
    primary/secondary families must belong to the intent's family set, the
    triple must carry the direction's signature primitives, and steampunk
    additionally requires warm metallic palette evidence.
    """
    instruction_text = str(instruction or "").casefold()
    active = [
        requirement
        for requirement in _INTENT_REQUIREMENTS.values()
        if any(_token_present(instruction_text, token) for token in requirement["tokens"])
    ]
    if not active or not graphs:
        return
    pairs = [
        (directions[index] if index < len(directions) else None, graph)
        for index, graph in enumerate(graphs)
    ]
    for requirement in active:
        allowed_families = frozenset(requirement["families"])
        for direction, _graph in pairs:
            if direction is None:
                continue
            used_families = {
                item for item in (direction.primary_family, direction.secondary_family) if item
            }
            if used_families and not used_families & allowed_families:
                raise ValueError(
                    "ART_DIRECTION_MISMATCH: instruction direction requires "
                    f"families {sorted(allowed_families)} but variant declares "
                    f"{direction.primary_family}"
                )
        required_primitives = frozenset(requirement["primitives"])
        graphs_with_primitives = sum(
            1
            for _direction, graph in pairs
            if {
                graph.panel_layer.primitive,
                *(item.primitive for item in graph.decoration_layers),
                *(item.primitive for item in graph.effect_layers),
            } & required_primitives
        )
        minimum = int(requirement.get("min_graphs_with_primitives", 2))
        if graphs_with_primitives < min(minimum, len(graphs)):
            raise ValueError(
                "ART_DIRECTION_MISMATCH: instruction direction requires "
                f"{sorted(required_primitives)} in at least {minimum} variants; "
                f"found {graphs_with_primitives}"
            )
        warm_minimum = int(requirement.get("min_graphs_warm_metallic", 0))
        if warm_minimum:
            warm = sum(1 for _d, graph in pairs if _warm_metallic_evidence(graph))
            if warm < min(warm_minimum, len(graphs)):
                raise ValueError(
                    "ART_DIRECTION_MISMATCH: instruction direction requires warm "
                    "brass/copper/gold palette evidence in at least "
                    f"{warm_minimum} variants; found {warm}"
                )


def _glow_enabled(graph: VisualDesignGraph) -> bool:
    glow = graph.text_layer.glow
    return bool(isinstance(glow, Mapping) and glow.get("enabled"))


def _shadow_enabled(graph: VisualDesignGraph) -> bool:
    shadow = graph.text_layer.shadow
    return bool(isinstance(shadow, Mapping) and shadow.get("enabled"))


def art_direction_manifest() -> list[dict[str, Any]]:
    return [
        {
            **template.to_manifest(),
            "required_signature_groups": [
                sorted(group) for group in _FAMILY_SIGNATURES.get(template.family_id, ())
            ],
        }
        for template in ART_DIRECTION_TEMPLATES.values()
    ]


def _direction(
    family: str,
    concept: str,
    *,
    intent: str,
    motion: str,
    composition: str,
    color: str,
    avoid: tuple[str, ...],
    secondary: str = "",
) -> ArtDirectionSpec:
    template = ART_DIRECTION_TEMPLATES[family]
    return ArtDirectionSpec(
        concept_name=concept,
        intent=intent,
        emotion="controlled, expressive, immediate",
        visual_language=template.display_name,
        reference_family=template.display_name,
        hierarchy=template.readability_rules,
        text_emphasis="The subtitle text is the primary visual subject",
        composition=composition,
        shape_language=template.recommended_composition,
        color_strategy=color,
        contrast_strategy="Adapt stroke, shadow, or panel opacity to background luminance and visual busyness",
        motion_concept=motion,
        entrance_feel=template.motion_vocabulary[0],
        hold_feel="stable readable hold",
        exit_feel=template.motion_vocabulary[-1],
        decoration_strategy="Use only layers that clarify the selected family; keep accents subordinate",
        effect_strategy="One dominant effect idea with staggered supporting layers",
        density=DecorationDensity.MEDIUM if DecorationDensity.MEDIUM in template.density_range else template.density_range[0],
        energy="CONTROLLED",
        readability="PRIMARY",
        avoid=avoid,
        primary_family=family,
        secondary_family=secondary,
        family_mix=(70, 30) if secondary else (100, 0),
        regeneration_anchor=family,
    ).validate()


def fallback_art_directions(instruction: str) -> tuple[ArtDirectionSpec, ...]:
    """Produce three structurally different semantic directions immediately."""

    text = str(instruction or "").casefold()
    common_avoid = (
        "continuous full-cue jitter",
        "full-screen decoration without explicit need",
        "all layers scaling at the same speed",
        "decoration heavier than subtitle text",
    )
    if any(token in text for token in ("glitch", "故障", "赛博", "signal", "hud")):
        families = ("CRT_GLITCH", "DATA_SCAN", "CLEAN_EDITORIAL")
    elif any(token in text for token in ("comic", "美漫", "漫画", "burst", "爆裂")):
        families = ("AMERICAN_COMIC_BURST", "MANGA_IMPACT", "HALFTONE_SLAM")
    elif any(token in text for token in ("game", "游戏", "主播", "直播", "achievement")):
        families = ("CRITICAL_HIT", "STREAMER_EMPHASIS", "ACHIEVEMENT_POP")
    elif any(token in text for token in (
        "蒸汽朋克", "steampunk", "维多利亚", "victorian", "黄铜", "brass",
        "齿轮", "gear", "机械", "蒸汽",
    )):
        families = ("INDUSTRIAL_BRASS_HUD", "VICTORIAN_MECHANICAL", "STEAM_GAUGE_TYPO")
    else:
        families = ("CLEAN_EDITORIAL", "MANGA_IMPACT", "DATA_SCAN")
    return tuple(
        _direction(
            family,
            ART_DIRECTION_TEMPLATES[family].display_name,
            intent=(str(instruction).strip() or "Create a readable, controlled subtitle treatment"),
            motion=" -> ".join(ART_DIRECTION_TEMPLATES[family].motion_vocabulary),
            composition=ART_DIRECTION_TEMPLATES[family].recommended_composition,
            color=ART_DIRECTION_TEMPLATES[family].color_constraints,
            avoid=common_avoid + ART_DIRECTION_TEMPLATES[family].forbidden_cheap_patterns[:2],
        )
        for family in families
    )


@dataclass(frozen=True)
class VisualQualityScore:
    readability: int
    hierarchy: int
    composition: int
    motion_quality: int
    effect_specificity: int
    visual_density: int
    renderer_support: int
    density_level: DecorationDensity
    issues: tuple[str, ...] = ()
    repaired: bool = False

    @property
    def accepted(self) -> bool:
        return bool(
            min(
                self.readability,
                self.hierarchy,
                self.composition,
                self.motion_quality,
                self.effect_specificity,
                self.visual_density,
                self.renderer_support,
            ) >= 55
            and not any(
                item in {"CHEAP_MOTION", "OVERDECORATED", "ART_DIRECTION_MISMATCH"}
                for item in self.issues
            )
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["density_level"] = self.density_level.value
        payload["issues"] = list(self.issues)
        payload["accepted"] = self.accepted
        return payload


def score_visual_graph(
    graph: VisualDesignGraph | Mapping[str, Any],
    direction: ArtDirectionSpec | None = None,
    *,
    repaired: bool = False,
) -> VisualQualityScore:
    graph = copy.deepcopy(graph) if isinstance(graph, VisualDesignGraph) else VisualDesignGraph.from_dict(graph)
    graph.validate()
    issues = list(readability_issues(graph))
    if direction is not None:
        issues.extend(art_direction_mismatches(graph, direction))
    readability = max(0, 100 - len(issues) * 24)
    layer_count = int(graph.panel_layer.primitive != "NONE") + len(graph.decoration_layers) + len(graph.effect_layers)
    density = DecorationDensity.LOW if layer_count <= 1 else DecorationDensity.MEDIUM if layer_count <= 5 else DecorationDensity.HIGH
    hierarchy = 100
    if len(graph.decoration_layers) > 4 or len(graph.effect_layers) > 2:
        hierarchy -= 35
    if layer_count > 7:
        hierarchy -= 30
        issues.append("OVERDECORATED")
    _x, _y, width, height = visual_composition_bounds((0, 0, 100, 40), graph)
    overflow = max((width - 100) / 200, (height - 40) / 80, 0)
    allowed_overflow = 0.60 if graph.panel_layer.primitive == "COMIC_BURST" else 0.35
    composition = 100 if overflow <= allowed_overflow else max(0, round(100 - (overflow - allowed_overflow) * 180))
    if composition < 55:
        issues.append("COMPOSITION_OVERFLOW")
    tracks = graph.motion_graph.tracks
    targets = {track.target for track in tracks}
    non_linear = sum(
        frame.easing != "linear" for track in tracks for frame in track.keyframes[1:]
    )
    motion_quality = min(100, 28 + len(tracks) * 8 + len(targets) * 7 + min(24, non_linear * 3)) if tracks else 40
    clean_editorial = bool(
        direction is not None and direction.primary_family == "CLEAN_EDITORIAL"
    )
    weak = is_weak_motion_graph(graph) and not clean_editorial
    if clean_editorial:
        motion_quality = max(70, motion_quality)
    specificity = 25 if weak else (
        90 if clean_editorial else
        min(100, 62 + len(graph.effect_layers) * 12 + len(targets - {"group"}) * 6)
    )
    if weak:
        issues.append("CHEAP_MOTION")
    density_score = 100
    if direction is not None and density != direction.density:
        density_score -= 18
    if layer_count > 7:
        density_score = min(density_score, 35)
    return VisualQualityScore(
        readability=max(0, readability),
        hierarchy=max(0, hierarchy),
        composition=max(0, composition),
        motion_quality=max(0, motion_quality),
        effect_specificity=max(0, specificity),
        visual_density=max(0, density_score),
        renderer_support=100,
        density_level=density,
        issues=tuple(dict.fromkeys(issues)),
        repaired=repaired,
    )


def validate_and_repair_graph(
    graph: VisualDesignGraph,
    direction: ArtDirectionSpec,
    *,
    deadline_ms: float = 40.0,
) -> tuple[VisualDesignGraph, VisualQualityScore]:
    """Run at most one deterministic repair within a strict local deadline."""

    started = time.perf_counter()
    candidate = copy.deepcopy(graph).validate()
    direction_repaired = False
    if direction is not None:
        try:
            validate_graph_for_direction(candidate, direction)
        except (TypeError, ValueError) as exc:
            # Unsupported renderer layers cannot survive the trusted graph
            # boundary. Other semantic mismatches still flow through the
            # normal quality repair below so family-specific motion repair is
            # not short-circuited.
            if "forbidden primitives" in str(exc):
                candidate = _repair_direction_mismatch(candidate, direction)
                direction_repaired = True
    score = score_visual_graph(candidate, direction, repaired=direction_repaired)
    if score.accepted:
        if direction is not None:
            try:
                validate_graph_for_direction(candidate, direction)
            except (TypeError, ValueError):
                candidate = _repair_direction_mismatch(candidate, direction)
                score = score_visual_graph(candidate, direction, repaired=True)
        return candidate, score
    if (time.perf_counter() - started) * 1000.0 >= deadline_ms:
        return candidate, score
    if "ART_DIRECTION_MISMATCH" in score.issues:
        candidate = _repair_direction_mismatch(candidate, direction)
    if "CHEAP_MOTION" in score.issues:
        candidate = repair_weak_motion_graph(candidate)
    if "OVERDECORATED" in score.issues:
        candidate.decoration_layers = candidate.decoration_layers[:4]
        candidate.effect_layers = candidate.effect_layers[:2]
    for layer in (candidate.panel_layer, *candidate.decoration_layers, *candidate.effect_layers):
        for key in ("opacity", "intensity", "flicker", "scanlineOpacity"):
            if key in layer.params:
                try:
                    layer.params[key] = min(float(layer.params[key]), 0.75)
                except (TypeError, ValueError):
                    pass
    candidate.validate()
    if direction is not None:
        try:
            validate_graph_for_direction(candidate, direction)
        except (TypeError, ValueError):
            candidate = _repair_direction_mismatch(candidate, direction)
    return candidate, score_visual_graph(candidate, direction, repaired=True)


def _repair_direction_mismatch(
    graph: VisualDesignGraph,
    direction: ArtDirectionSpec,
) -> VisualDesignGraph:
    """Use the one local repair to make declared semantics structurally true."""

    duration = max(900, int(graph.motion_graph.duration_ms or 2_400))
    graph.motion_graph.duration_ms = duration
    family = direction.primary_family
    family_ids = tuple(
        item for item in (direction.primary_family, direction.secondary_family)
        if item in ART_DIRECTION_TEMPLATES
    )
    allowed = {"NONE"}
    for family_id in family_ids:
        allowed.update(ART_DIRECTION_TEMPLATES[family_id].allowed_layers)
    removed_ids = {
        item.id for item in (*graph.decoration_layers, *graph.effect_layers)
        if item.primitive not in allowed
    }
    graph.decoration_layers = [
        item for item in graph.decoration_layers if item.primitive in allowed
    ]
    graph.effect_layers = [
        item for item in graph.effect_layers if item.primitive in allowed
    ]
    graph.motion_graph.tracks = [
        track for track in graph.motion_graph.tracks if track.target not in removed_ids
    ]
    if graph.panel_layer.primitive not in allowed:
        vocabulary = ART_DIRECTION_TEMPLATES[family].panel_vocabulary
        graph.panel_layer.primitive = next(
            (item for item in vocabulary if item in allowed), "NONE",
        )
        if graph.panel_layer.primitive == "NONE":
            graph.panel_layer.params = {}
    effect_text = f"{direction.effect_strategy} {direction.motion_concept}".casefold()
    wants_glitch = "GLITCH" in allowed and (
        family in {"CRT_GLITCH", "SIGNAL_LOSS"} or any(
            token in str(direction.effect_strategy).casefold()
            for token in ("glitch", "故障")
        )
    )
    if wants_glitch:
        glitch = next((item for item in graph.effect_layers if item.primitive == "GLITCH"), None)
        if glitch is None:
            glitch = EffectLayer(
                "glitch", "GLITCH",
                {"rgbOffset": 7, "sliceCount": 5, "sliceDisplacement": 10, "flicker": 0.12},
                graph.seed + 31,
            )
            graph.effect_layers.append(glitch)
        if not any(track.target == glitch.id for track in graph.motion_graph.tracks):
            graph.motion_graph.tracks.append(MotionTrack(
                glitch.id, "rgb_offset", [
                    MotionKeyframe(0, 8, "glitch"),
                    MotionKeyframe(min(180, duration), 0, "ease-out-expo"),
                    MotionKeyframe(max(181, duration - 180), 0, "linear"),
                    MotionKeyframe(duration, 0, "linear"),
                ],
            ))
    wants_scan = any(token in effect_text for token in ("scan", "扫描"))
    if wants_scan and not wants_glitch:
        scan = next(
            (item for item in graph.decoration_layers if item.primitive == "SCANLINES"),
            None,
        )
        if scan is None:
            scan = DecorationLayer(
                "scanlines", "SCANLINES",
                {"spacing": 6, "opacity": 0.24, "color": "#8820E8FF"},
                graph.seed + 37,
            )
            graph.decoration_layers.append(scan)
        if not any(track.target == scan.id for track in graph.motion_graph.tracks):
            graph.motion_graph.tracks.append(MotionTrack(
                scan.id, "scanline_opacity", [
                    MotionKeyframe(0, 0, "linear"),
                    MotionKeyframe(min(220, duration), 0.42, "ease-out"),
                    MotionKeyframe(max(221, duration - 160), 0.18, "linear"),
                    MotionKeyframe(duration, 0, "ease-in"),
                ],
            ))
    wants_impact = bool(
        allowed.intersection({"IMPACT", "IMPACT_RAYS", "SHARDS"})
    ) and (
        family in {
            "AMERICAN_COMIC_BURST", "MANGA_IMPACT", "SPEEDLINE_PUNCH",
            "CRITICAL_HIT", "ACHIEVEMENT_POP", "STREAMER_EMPHASIS",
        } or any(token in effect_text for token in ("impact", "冲击"))
    )
    if wants_impact:
        target = next(
            (item for item in (*graph.effect_layers, *graph.decoration_layers)
             if item.primitive in {"IMPACT", "IMPACT_RAYS", "SHARDS"}),
            None,
        )
        if target is None:
            if "IMPACT_RAYS" in allowed:
                target = DecorationLayer(
                    "impact-rays", "IMPACT_RAYS",
                    {"count": 14, "length": 32, "color": "#99FFFFFF"},
                    graph.seed + 43,
                )
                graph.decoration_layers.append(target)
            elif "SHARDS" in allowed:
                target = DecorationLayer(
                    "impact-shards", "SHARDS",
                    {"count": 8, "spread": 26, "color": "#99FFFFFF"},
                    graph.seed + 43,
                )
                graph.decoration_layers.append(target)
            else:
                target = EffectLayer(
                    "impact", "IMPACT",
                    {"shakePx": 3, "durationMs": 280},
                    graph.seed + 43,
                )
                graph.effect_layers.append(target)
        if not any(track.target == target.id for track in graph.motion_graph.tracks):
            graph.motion_graph.tracks.append(MotionTrack(
                target.id, "ray_scale", [
                    MotionKeyframe(0, 0.65, "ease-out"),
                    MotionKeyframe(min(260, duration), 1.0, "impact"),
                    MotionKeyframe(max(261, duration - 180), 1.0, "linear"),
                    MotionKeyframe(duration, 0.82, "ease-in"),
                ],
            ))
    wants_shards = any(token in effect_text for token in ("shard", "碎片"))
    if wants_shards:
        shards = next(
            (item for item in graph.decoration_layers if item.primitive == "SHARDS"),
            None,
        )
        if shards is None and "SHARDS" in ART_DIRECTION_TEMPLATES[family].allowed_layers:
            shards = DecorationLayer(
                "shards", "SHARDS",
                {"count": 8, "spread": 28, "color": "#AAFFFFFF"},
                graph.seed + 47,
            )
            graph.decoration_layers.append(shards)
        if shards is not None and not any(
            track.target == shards.id for track in graph.motion_graph.tracks
        ):
            graph.motion_graph.tracks.append(MotionTrack(
                shards.id, "scale", [
                    MotionKeyframe(0, 0.55, "ease-out"),
                    MotionKeyframe(min(260, duration), 1.0, "impact"),
                    MotionKeyframe(max(261, duration - 180), 1.0, "linear"),
                    MotionKeyframe(duration, 0.85, "ease-in"),
                ],
            ))
    if direction.primary_family != "CLEAN_EDITORIAL" and not graph.motion_graph.tracks:
        graph.motion_graph.tracks.append(MotionTrack(
            "group", "opacity", [
                MotionKeyframe(0, 0, "linear"),
                MotionKeyframe(min(180, duration), 1, "ease-out-expo"),
                MotionKeyframe(max(181, duration - 180), 1, "linear"),
                MotionKeyframe(duration, 0, "ease-in"),
            ],
        ))
    return graph.validate()


__all__ = [
    "ART_DIRECTION_SCHEMA", "ART_DIRECTION_TEMPLATES", "ART_DIRECTION_VERSION",
    "ArtDirectionSpec", "ArtDirectionTemplate", "DecorationDensity",
    "VisualQualityScore", "art_direction_manifest", "art_direction_mismatches",
    "fallback_art_directions",
    "score_visual_graph", "validate_and_repair_graph", "validate_graph_for_direction",
]
