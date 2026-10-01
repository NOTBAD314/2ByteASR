"""Versioned, renderer-neutral layered visual design graph."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable, Mapping

from PySide6.QtGui import QColor


GRAPH_SCHEMA = "2byte.visual-design-graph"
GRAPH_VERSION = 1

PANEL_PRIMITIVES = frozenset({
    "NONE", "ROUNDED_PANEL", "RECTANGLE", "COMIC_BURST", "BADGE", "RIBBON",
    "CUT_CORNER", "ANGLED_PLATE", "BRACKET_FRAME", "TECH_FRAME",
    "COMIC_BUBBLE", "UNDERLINE_SLAB", "MARKER", "TAPE", "PIXEL_FRAME",
    "PILL", "TORN_PAPER", "GLASS_PANEL", "MECHANICAL_PLATE", "STICKER",
    "LOWER_THIRD",
})
DECORATION_PRIMITIVES = frozenset({
    "IMPACT_RAYS", "SPEED_LINES", "HALFTONE", "SHARDS", "ACCENT_BARS", "SCANLINES",
    "PIXEL_TILES", "CROSSHAIR", "INK_SPLAT", "FLOAT_GLYPHS",
    "SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS",
    "GEARS", "RIVETS", "GAUGE", "PIPES", "STEAM",
})
EFFECT_PRIMITIVES = frozenset({"GLITCH", "IMPACT", "RGB_SPLIT"})
MOTION_PROPERTIES = frozenset({
    "x", "y", "scale", "scale_x", "scale_y", "rotation", "opacity",
    "rgb_offset", "slice_offset", "scanline_opacity", "flicker", "ray_scale",
    "burst_scale", "shake_x", "shake_y", "tracking", "char_reveal",
    "blur", "mask_reveal",
})
# Properties whose untouched value is 1 rather than 0; both live compositors
# must treat these identically or an omitted track blanks the layer.
UNIT_DEFAULT_PROPERTIES = frozenset({
    "scale", "scale_x", "scale_y", "opacity", "ray_scale", "burst_scale",
    "char_reveal", "mask_reveal",
})
MOTION_EASINGS = frozenset({
    "linear", "ease-in", "ease-out", "ease-in-out", "overshoot", "step",
    "easeoutexpo", "ease-out-expo", "easeoutback", "ease-out-back",
    "spring", "dampedspring", "damped-spring", "easeinoutcubic",
    "ease-in-out-cubic", "impact", "impactcurve", "glitch",
})
MOTION_POST_BEHAVIORS = frozenset({"HOLD", "RESET"})
CHEAP_MOTION_PROPERTIES = frozenset({
    "x", "y", "scale", "scale_x", "scale_y", "rotation", "opacity",
})
EFFECT_FAMILIES = (
    "IMPACT", "COMIC_BURST", "GLITCH_DIGITAL", "GLITCH_SIGNAL_LOSS",
    "STREAMER_POP", "PUNCH", "TYPE_STAGGER",
)
COORDINATE_SPACE_TEXT = "subtitle-content-box"
COORDINATE_SPACE_SUBTITLE_LOCAL = "subtitle-local"
COORDINATE_SPACE_VIDEO_CANVAS = "video-canvas"
COORDINATE_SPACES = frozenset({
    COORDINATE_SPACE_TEXT, COORDINATE_SPACE_SUBTITLE_LOCAL, COORDINATE_SPACE_VIDEO_CANVAS,
})
FORBIDDEN_GRAPH_KEYS = frozenset({
    "code", "source", "component", "raw", "raw_ass", "rawAss", "react",
    "javascript", "typescript", "script", "executable",
})


class VisualDesignGraphValidationError(ValueError):
    pass


def _safe_json(value: Any, path: str = "graph", depth: int = 0) -> None:
    if depth > 10:
        raise VisualDesignGraphValidationError(f"{path} is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            key = str(key)
            if key in FORBIDDEN_GRAPH_KEYS:
                raise VisualDesignGraphValidationError(
                    f"{path}.{key} cannot contain renderer code"
                )
            _safe_json(item, f"{path}.{key}", depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise VisualDesignGraphValidationError(f"{path} contains too many items")
        for index, item in enumerate(value):
            _safe_json(item, f"{path}[{index}]", depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise VisualDesignGraphValidationError(f"{path} contains a non-JSON value")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise VisualDesignGraphValidationError(f"{path} must be an object")
    return copy.deepcopy(dict(value))


def _number(value: Any, path: str, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise VisualDesignGraphValidationError(f"{path} must be a number") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise VisualDesignGraphValidationError(f"{path} out of range")
    return result


def _color(value: Any, path: str) -> str:
    result = str(value or "")
    if not (
        result.startswith("#")
        and len(result) in {7, 9}
        and all(char in "0123456789abcdefABCDEF" for char in result[1:])
    ):
        raise VisualDesignGraphValidationError(f"{path} must be #RRGGBB or #AARRGGBB")
    return result.upper()


@dataclass
class TextLayer:
    id: str = "text"
    font: dict[str, Any] = field(default_factory=dict)
    fill: dict[str, Any] = field(
        default_factory=lambda: {"type": "solid", "color": "#FFFFFFFF"}
    )
    strokes: list[dict[str, Any]] = field(default_factory=list)
    shadow: dict[str, Any] = field(default_factory=dict)
    glow: dict[str, Any] = field(default_factory=dict)
    letter_spacing: float = 0.0
    line_spacing: float = 1.0
    alignment: int = 2
    emphasis: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TextLayer":
        self.id = str(self.id or "text").strip()
        if not self.id:
            raise VisualDesignGraphValidationError("textLayer.id is required")
        self.font = _mapping(self.font, "textLayer.font")
        unknown_font = set(self.font) - {"family", "size", "weight", "italic"}
        if unknown_font:
            raise VisualDesignGraphValidationError(
                f"textLayer.font has unknown fields: {sorted(unknown_font)}"
            )
        self.font = {
            "family": str(self.font.get("family") or "Microsoft YaHei UI"),
            "size": _number(self.font.get("size", 52), "textLayer.font.size", 8, 500),
            "weight": int(_number(
                self.font.get("weight", 400), "textLayer.font.weight", 100, 1000
            )),
            **({"italic": bool(self.font.get("italic"))} if "italic" in self.font else {}),
        }
        self.fill = _mapping(self.fill, "textLayer.fill")
        fill_type = str(self.fill.get("type") or "solid").lower()
        if fill_type == "solid":
            self.fill = {
                "type": "solid",
                "color": _color(self.fill.get("color", "#FFFFFFFF"), "textLayer.fill.color"),
            }
        elif fill_type in {"linear", "linear-gradient", "radial", "radial-gradient"}:
            stops = list(self.fill.get("stops") or ())
            if not 2 <= len(stops) <= 8:
                raise VisualDesignGraphValidationError("textLayer.fill requires 2-8 stops")
            normalized = []
            for index, stop in enumerate(stops):
                stop = _mapping(stop, f"textLayer.fill.stops[{index}]")
                normalized.append({
                    "position": _number(
                        stop.get("position", stop.get("pos", index / max(1, len(stops) - 1))),
                        f"textLayer.fill.stops[{index}].position", 0, 1,
                    ),
                    "color": _color(
                        stop.get("color"), f"textLayer.fill.stops[{index}].color"
                    ),
                })
            self.fill = {
                "type": "radial-gradient" if "radial" in fill_type else "linear-gradient",
                "angle": _number(self.fill.get("angle", 0), "textLayer.fill.angle", -3600, 3600),
                "stops": normalized,
            }
        else:
            raise VisualDesignGraphValidationError("textLayer.fill.type is unsupported")
        if not isinstance(self.strokes, list) or len(self.strokes) > 4:
            raise VisualDesignGraphValidationError("textLayer.strokes must contain at most 4 layers")
        normalized_strokes = []
        for index, stroke in enumerate(self.strokes):
            stroke = _mapping(stroke, f"textLayer.strokes[{index}]")
            alignment = str(stroke.get("alignment") or "OUTSIDE").upper()
            if alignment != "OUTSIDE":
                raise VisualDesignGraphValidationError(
                    f"textLayer.strokes[{index}].alignment is not supported"
                )
            normalized_strokes.append({
                **stroke,
                "color": _color(
                    stroke.get("color", "#FF000000"),
                    f"textLayer.strokes[{index}].color",
                ),
                "width": _number(
                    stroke.get("width", 0), f"textLayer.strokes[{index}].width", 0, 40
                ),
                "opacity": _number(
                    stroke.get("opacity", 1), f"textLayer.strokes[{index}].opacity", 0, 1
                ),
                "alignment": alignment,
            })
        self.strokes = normalized_strokes
        self.shadow = _mapping(self.shadow, "textLayer.shadow")
        self.glow = _mapping(self.glow, "textLayer.glow")
        self.emphasis = _mapping(self.emphasis, "textLayer.emphasis")
        self.letter_spacing = _number(
            self.letter_spacing, "textLayer.letterSpacing", -20, 80
        )
        self.line_spacing = _number(self.line_spacing, "textLayer.lineSpacing", 0.5, 4)
        self.alignment = int(_number(self.alignment, "textLayer.alignment", 1, 9))
        _safe_json(self.to_dict(validate=False), "textLayer")
        return self

    def to_dict(self, *, validate: bool = True) -> dict[str, Any]:
        if validate:
            self.validate()
        return {
            "id": self.id,
            "font": copy.deepcopy(self.font),
            "fill": copy.deepcopy(self.fill),
            "strokes": copy.deepcopy(self.strokes),
            "shadow": copy.deepcopy(self.shadow),
            "glow": copy.deepcopy(self.glow),
            "letterSpacing": self.letter_spacing,
            "lineSpacing": self.line_spacing,
            "alignment": self.alignment,
            "emphasis": copy.deepcopy(self.emphasis),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TextLayer":
        value = _mapping(payload, "textLayer")
        unknown = set(value) - {
            "id", "font", "fill", "strokes", "shadow", "glow",
            "letterSpacing", "lineSpacing", "alignment", "emphasis",
        }
        if unknown:
            raise VisualDesignGraphValidationError(
                f"textLayer has unknown fields: {sorted(unknown)}"
            )
        return cls(
            id=str(value.get("id") or "text"),
            font=_mapping(value.get("font"), "textLayer.font"),
            fill=_mapping(value.get("fill") or {"type": "solid", "color": "#FFFFFFFF"}, "textLayer.fill"),
            strokes=copy.deepcopy(list(value.get("strokes") or ())),
            shadow=_mapping(value.get("shadow"), "textLayer.shadow"),
            glow=_mapping(value.get("glow"), "textLayer.glow"),
            letter_spacing=value.get("letterSpacing", 0),
            line_spacing=value.get("lineSpacing", 1),
            alignment=value.get("alignment", 2),
            emphasis=_mapping(value.get("emphasis"), "textLayer.emphasis"),
        ).validate()


@dataclass
class PanelLayer:
    id: str = "panel"
    primitive: str = "NONE"
    params: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "PanelLayer":
        self.id = str(self.id or "panel").strip()
        self.primitive = str(self.primitive or "NONE").upper()
        if self.primitive not in PANEL_PRIMITIVES:
            raise VisualDesignGraphValidationError(
                f"unsupported panel primitive: {self.primitive}"
            )
        self.params = _mapping(self.params, "panelLayer.params")
        _safe_json(self.params, "panelLayer.params")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"id": self.id, "primitive": self.primitive, "params": copy.deepcopy(self.params)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "PanelLayer":
        value = _mapping(payload, "panelLayer")
        return cls(
            str(value.get("id") or "panel"),
            str(value.get("primitive") or "NONE"),
            _mapping(value.get("params"), "panelLayer.params"),
        ).validate()


@dataclass
class DecorationLayer:
    id: str
    primitive: str
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 0

    def validate(self) -> "DecorationLayer":
        self.id = str(self.id or "").strip()
        if not self.id:
            raise VisualDesignGraphValidationError("decoration layer id is required")
        self.primitive = str(self.primitive or "").upper()
        if self.primitive not in DECORATION_PRIMITIVES:
            raise VisualDesignGraphValidationError(
                f"unsupported decoration primitive: {self.primitive}"
            )
        self.params = _mapping(self.params, f"decorationLayers.{self.id}.params")
        self.seed = int(_number(self.seed, f"decorationLayers.{self.id}.seed", 0, 2**31 - 1))
        _safe_json(self.params, f"decorationLayers.{self.id}.params")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id, "primitive": self.primitive,
            "params": copy.deepcopy(self.params), "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecorationLayer":
        value = _mapping(payload, "decorationLayer")
        return cls(
            str(value.get("id") or ""), str(value.get("primitive") or ""),
            _mapping(value.get("params"), "decorationLayer.params"), value.get("seed", 0),
        ).validate()


@dataclass
class EffectLayer:
    id: str
    primitive: str
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 0

    def validate(self) -> "EffectLayer":
        self.id = str(self.id or "").strip()
        if not self.id:
            raise VisualDesignGraphValidationError("effect layer id is required")
        self.primitive = str(self.primitive or "").upper()
        if self.primitive not in EFFECT_PRIMITIVES:
            raise VisualDesignGraphValidationError(
                f"unsupported effect primitive: {self.primitive}"
            )
        self.params = _mapping(self.params, f"effectLayers.{self.id}.params")
        self.seed = int(_number(self.seed, f"effectLayers.{self.id}.seed", 0, 2**31 - 1))
        _safe_json(self.params, f"effectLayers.{self.id}.params")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id, "primitive": self.primitive,
            "params": copy.deepcopy(self.params), "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLayer":
        value = _mapping(payload, "effectLayer")
        return cls(
            str(value.get("id") or ""), str(value.get("primitive") or ""),
            _mapping(value.get("params"), "effectLayer.params"), value.get("seed", 0),
        ).validate()


@dataclass(frozen=True)
class MotionKeyframe:
    time_ms: int
    value: float
    easing: str = "linear"

    def validate(self, path: str = "motion.keyframe") -> "MotionKeyframe":
        time_ms = int(_number(self.time_ms, f"{path}.timeMs", 0, 30_000))
        value = _number(self.value, f"{path}.value", -100_000, 100_000)
        easing = str(self.easing or "linear").lower()
        if easing not in MOTION_EASINGS:
            raise VisualDesignGraphValidationError(f"{path}.easing is unsupported")
        return MotionKeyframe(time_ms, value, easing)

    def to_dict(self) -> dict[str, Any]:
        value = self.validate()
        return {"timeMs": value.time_ms, "value": value.value, "easing": value.easing}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], path: str) -> "MotionKeyframe":
        value = _mapping(payload, path)
        return cls(
            value.get("timeMs", value.get("t", 0)), value.get("value", 0),
            str(value.get("easing") or "linear"),
        ).validate(path)


@dataclass
class MotionTrack:
    target: str
    property: str
    keyframes: list[MotionKeyframe] = field(default_factory=list)
    post_behavior: str = "HOLD"

    def validate(self, known_targets: set[str] | None = None) -> "MotionTrack":
        self.target = str(self.target or "").strip()
        self.property = str(self.property or "").strip()
        if not self.target or (known_targets is not None and self.target not in known_targets):
            raise VisualDesignGraphValidationError(
                f"motionGraph track target is unknown: {self.target}"
            )
        if self.property not in MOTION_PROPERTIES:
            raise VisualDesignGraphValidationError(
                f"motionGraph property is unsupported: {self.property}"
            )
        self.post_behavior = str(self.post_behavior or "HOLD").upper()
        if self.post_behavior not in MOTION_POST_BEHAVIORS:
            raise VisualDesignGraphValidationError(
                f"motionGraph post behavior is unsupported: {self.post_behavior}"
            )
        if not isinstance(self.keyframes, list) or not 1 <= len(self.keyframes) <= 64:
            raise VisualDesignGraphValidationError("motionGraph track requires 1-64 keyframes")
        normalized = [
            frame.validate(f"motionGraph.{self.target}.{self.property}[{index}]")
            if isinstance(frame, MotionKeyframe)
            else MotionKeyframe.from_dict(
                frame, f"motionGraph.{self.target}.{self.property}[{index}]"
            )
            for index, frame in enumerate(self.keyframes)
        ]
        self.keyframes = sorted(normalized, key=lambda frame: frame.time_ms)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "target": self.target, "property": self.property,
            "keyframes": [frame.to_dict() for frame in self.keyframes],
            "postBehavior": self.post_behavior,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MotionTrack":
        value = _mapping(payload, "motionTrack")
        return cls(
            str(value.get("target") or ""), str(value.get("property") or ""),
            [
                MotionKeyframe.from_dict(frame, f"motionTrack.keyframes[{index}]")
                for index, frame in enumerate(value.get("keyframes") or ())
            ],
            str(value.get("postBehavior") or "HOLD"),
        )


@dataclass
class MotionGraph:
    duration_ms: int = 2_400
    tracks: list[MotionTrack] = field(default_factory=list)
    stagger_ms: int = 0

    def validate(self, known_targets: set[str] | None = None) -> "MotionGraph":
        self.duration_ms = int(_number(self.duration_ms, "motionGraph.durationMs", 1, 30_000))
        self.stagger_ms = int(_number(self.stagger_ms, "motionGraph.staggerMs", 0, 5_000))
        if not isinstance(self.tracks, list) or len(self.tracks) > 96:
            raise VisualDesignGraphValidationError("motionGraph has too many tracks")
        self.tracks = [track.validate(known_targets) for track in self.tracks]
        if any(frame.time_ms > self.duration_ms for track in self.tracks for frame in track.keyframes):
            raise VisualDesignGraphValidationError("motionGraph keyframe exceeds duration")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "durationMs": self.duration_ms,
            "staggerMs": self.stagger_ms,
            "tracks": [track.to_dict() for track in self.tracks],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "MotionGraph":
        value = _mapping(payload, "motionGraph")
        return cls(
            value.get("durationMs", 2_400),
            [MotionTrack.from_dict(track) for track in value.get("tracks") or ()],
            value.get("staggerMs", 0),
        )


@dataclass
class VisualDesignGraph:
    name: str
    text_layer: TextLayer = field(default_factory=TextLayer)
    panel_layer: PanelLayer = field(default_factory=PanelLayer)
    decoration_layers: list[DecorationLayer] = field(default_factory=list)
    effect_layers: list[EffectLayer] = field(default_factory=list)
    motion_graph: MotionGraph = field(default_factory=MotionGraph)
    seed: int = 0
    version: int = GRAPH_VERSION
    schema: str = GRAPH_SCHEMA

    def validate(self) -> "VisualDesignGraph":
        self.schema = str(self.schema or GRAPH_SCHEMA)
        self.version = int(self.version)
        if self.schema != GRAPH_SCHEMA or self.version != GRAPH_VERSION:
            raise VisualDesignGraphValidationError("unsupported VisualDesignGraph schema/version")
        self.name = str(self.name or "").strip()
        if not self.name or len(self.name) > 120:
            raise VisualDesignGraphValidationError("graph name is required and must be short")
        self.seed = int(_number(self.seed, "seed", 0, 2**31 - 1))
        self.text_layer.validate()
        self.panel_layer.validate()
        if not isinstance(self.decoration_layers, list) or len(self.decoration_layers) > 24:
            raise VisualDesignGraphValidationError("too many decoration layers")
        if not isinstance(self.effect_layers, list) or len(self.effect_layers) > 12:
            raise VisualDesignGraphValidationError("too many effect layers")
        self.decoration_layers = [item.validate() for item in self.decoration_layers]
        self.effect_layers = [item.validate() for item in self.effect_layers]
        ids = [
            "group", self.text_layer.id, self.panel_layer.id,
            *(item.id for item in self.decoration_layers),
            *(item.id for item in self.effect_layers),
        ]
        if len(ids) != len(set(ids)):
            raise VisualDesignGraphValidationError("layer ids must be unique")
        self.motion_graph.validate(set(ids))
        _safe_json(self.to_dict(validate=False))
        return self

    def to_dict(self, *, validate: bool = True) -> dict[str, Any]:
        if validate:
            self.validate()
        return {
            "schema": self.schema,
            "version": self.version,
            "name": self.name,
            "seed": self.seed,
            "textLayer": self.text_layer.to_dict(validate=False),
            "panelLayer": self.panel_layer.to_dict(),
            "decorationLayers": [item.to_dict() for item in self.decoration_layers],
            "effectLayers": [item.to_dict() for item in self.effect_layers],
            "motionGraph": self.motion_graph.to_dict(),
        }

    def stable_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VisualDesignGraph":
        value = _mapping(payload, "VisualDesignGraph")
        unknown = set(value) - {
            "schema", "version", "name", "seed", "textLayer", "panelLayer",
            "decorationLayers", "effectLayers", "motionGraph",
        }
        if unknown:
            raise VisualDesignGraphValidationError(
                f"VisualDesignGraph has unknown fields: {sorted(unknown)}"
            )
        return cls(
            name=str(value.get("name") or ""),
            text_layer=TextLayer.from_dict(value.get("textLayer") or {}),
            panel_layer=PanelLayer.from_dict(value.get("panelLayer")),
            decoration_layers=[
                DecorationLayer.from_dict(item)
                for item in value.get("decorationLayers") or ()
            ],
            effect_layers=[
                EffectLayer.from_dict(item) for item in value.get("effectLayers") or ()
            ],
            motion_graph=MotionGraph.from_dict(value.get("motionGraph")),
            seed=value.get("seed", 0),
            version=value.get("version", 0),
            schema=str(value.get("schema") or ""),
        ).validate()


def _legacy_motion_tracks(motion: Mapping[str, Any]) -> list[MotionTrack]:
    entrance = motion.get("entrance", motion.get("entry", {}))
    exit_part = motion.get("exit", {})
    entrance = entrance if isinstance(entrance, Mapping) else {}
    exit_part = exit_part if isinstance(exit_part, Mapping) else {}
    enter_ms = max(1, int(entrance.get("duration_ms", entrance.get("duration", 220)) or 220))
    exit_ms = max(1, int(exit_part.get("duration_ms", exit_part.get("duration", 180)) or 180))
    duration = max(600, int(motion.get("duration_ms", 2_400) or 2_400))
    tracks: list[MotionTrack] = []
    enter_type = str(entrance.get("type", entrance.get("preset", "none"))).casefold()
    exit_type = str(exit_part.get("type", exit_part.get("preset", "none"))).casefold()
    if enter_type not in {"", "none"}:
        tracks.append(MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(enter_ms, 1, "ease-out"),
        ]))
    if any(token in enter_type for token in ("pop", "impact", "bounce", "scale", "overshoot")):
        tracks.append(MotionTrack("group", "scale", [
            MotionKeyframe(0, 0.72, "overshoot"),
            MotionKeyframe(min(enter_ms, 180), 1.12, "ease-out"),
            MotionKeyframe(enter_ms, 1, "ease-in-out"),
        ]))
    elif "slide" in enter_type:
        tracks.append(MotionTrack("group", "y", [
            MotionKeyframe(0, 28, "ease-out"), MotionKeyframe(enter_ms, 0, "ease-out"),
        ]))
    if exit_type not in {"", "none"}:
        tracks.append(MotionTrack("group", "opacity", [
            MotionKeyframe(max(0, duration - exit_ms), 1, "ease-in"),
            MotionKeyframe(duration, 0, "ease-in"),
        ]))
    return tracks


def graph_from_style_recipe(recipe: Any) -> VisualDesignGraph:
    """Compile a legacy StyleRecipe into the layered V1 graph."""
    if isinstance(recipe, Mapping):
        from .style_recipe import StyleRecipe

        recipe = StyleRecipe.from_dict(recipe)
    recipe.validate()
    embedded = getattr(recipe, "visual_graph", {})
    if embedded:
        return VisualDesignGraph.from_dict(embedded)
    colors = recipe.colors if isinstance(recipe.colors, Mapping) else {}
    outline = recipe.outline if isinstance(recipe.outline, Mapping) else {}
    effects = recipe.effects if isinstance(recipe.effects, Mapping) else {}
    strokes = list(outline.get("layers") or ())
    if not strokes and float(outline.get("width", 0) or 0) > 0:
        strokes = [{
            "color": outline.get("color", colors.get("outline", "#FF000000")),
            "width": outline.get("width", 3),
        }]
    background = recipe.background if isinstance(recipe.background, Mapping) else {}
    panel_primitive = "NONE"
    if background.get("enabled"):
        background_type = str(background.get("type") or "rounded_panel").casefold()
        panel_primitive = {
            "comic_burst": "COMIC_BURST", "burst": "COMIC_BURST",
            "rectangle": "RECTANGLE", "badge": "BADGE", "ribbon": "RIBBON",
            "cut_corner": "CUT_CORNER", "angled_plate": "ANGLED_PLATE",
            "bracket_frame": "BRACKET_FRAME", "tech_frame": "TECH_FRAME",
            "comic_bubble": "COMIC_BUBBLE", "underline_slab": "UNDERLINE_SLAB",
        }.get(background_type, "ROUNDED_PANEL")
    decorations = []
    for index, item in enumerate(effects.get("decorations") or ()):
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("primitive", item.get("type", "ACCENT_BARS"))).upper()
        aliases = {
            "IMPACT_RAYS": "IMPACT_RAYS", "SPEED_LINES": "SPEED_LINES",
            "HALFTONE": "HALFTONE", "SHARDS": "SHARDS", "SCANLINE": "SCANLINES",
        }
        decorations.append(DecorationLayer(
            f"decoration-{index}", aliases.get(kind, "ACCENT_BARS"), dict(item), index,
        ))
    effect_layers = []
    motion_text = json.dumps(recipe.motion, ensure_ascii=False).casefold()
    if "glitch" in motion_text:
        effect_layers.append(EffectLayer("glitch", "GLITCH", {
            "rgbOffset": 6, "sliceCount": 5, "scanlineOpacity": 0.18,
        }, 74))
    if "impact" in motion_text:
        effect_layers.append(EffectLayer("impact", "IMPACT", {
            "shakePx": 3, "durationMs": 280,
        }, 41))
    graph = VisualDesignGraph(
        name=recipe.name,
        text_layer=TextLayer(
            font={
                "family": recipe.typography.get("fontFamily", "Microsoft YaHei UI"),
                "size": recipe.typography.get("fontSize", 52),
                "weight": 700 if recipe.typography.get("bold") else 400,
                "italic": bool(recipe.typography.get("italic", False)),
            },
            fill=(
                copy.deepcopy(colors.get("fill"))
                if isinstance(colors.get("fill"), Mapping)
                else {"type": "solid", "color": str(colors.get("fill") or "#FFFFFFFF")}
            ),
            strokes=copy.deepcopy(strokes),
            shadow=copy.deepcopy(outline.get("shadow") or {}),
            glow=copy.deepcopy(effects.get("glow") or {}),
            letter_spacing=float(recipe.typography.get("spacing", 0) or 0),
            line_spacing=float(recipe.typography.get("lineSpacing", 1) or 1),
            alignment=int(recipe.layout.get("alignment", 2) or 2),
            emphasis=copy.deepcopy(recipe.word_highlight),
        ),
        panel_layer=PanelLayer("panel", panel_primitive, copy.deepcopy(dict(background))),
        decoration_layers=decorations,
        effect_layers=effect_layers,
        motion_graph=MotionGraph(2_400, _legacy_motion_tracks(recipe.motion)),
        seed=0,
    )
    return graph.validate()


def style_recipe_from_graph(graph: VisualDesignGraph | Mapping[str, Any]):
    """Compile V1 into the existing render contract while preserving the graph."""
    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    from .style_recipe import StyleRecipe

    text = graph.text_layer
    font = text.font
    strokes = copy.deepcopy(text.strokes) or [{"color": "#FF000000", "width": 3}]
    panel = graph.panel_layer
    background = copy.deepcopy(panel.params)
    background["enabled"] = panel.primitive != "NONE"
    if panel.primitive != "NONE":
        background["type"] = panel.primitive.casefold()
    decorations = [
        {"type": item.primitive.casefold(), **copy.deepcopy(item.params), "seed": item.seed}
        for item in graph.decoration_layers
    ]
    effects = {
        "glow": copy.deepcopy(text.glow),
        "decorations": decorations,
        "visualEffects": [item.to_dict() for item in graph.effect_layers],
    }
    motion = {
        "mode": "explicit" if graph.motion_graph.tracks else "none",
        "origin": "visual_graph" if graph.motion_graph.tracks else "none",
        "graph": graph.motion_graph.to_dict(),
    }
    first = strokes[0]
    recipe = StyleRecipe(
        name=graph.name,
        engine="remotion" if (
            panel.primitive not in {"NONE", "RECTANGLE", "ROUNDED_PANEL"}
            or graph.decoration_layers or graph.effect_layers or len(strokes) > 1
            or text.fill.get("type") != "solid"
        ) else "native",
        typography={
            "fontFamily": font.get("family", "Microsoft YaHei UI"),
            "fontSize": font.get("size", 52),
            "bold": int(font.get("weight", 400) or 400) >= 700,
            "italic": bool(font.get("italic", False)),
            "spacing": text.letter_spacing,
            "lineSpacing": text.line_spacing,
        },
        layout={"alignment": text.alignment, "marginV": 64},
        colors={
            "fill": copy.deepcopy(text.fill),
            "outline": first.get("color", "#FF000000"),
            "background": background.get("color", "#00000000"),
        },
        outline={
            "layers": strokes, "color": first.get("color", "#FF000000"),
            "width": first.get("width", 3), "alignment": first.get("alignment", "OUTSIDE"),
            "shadow": copy.deepcopy(text.shadow),
        },
        background=background,
        motion=motion,
        word_highlight=copy.deepcopy(text.emphasis),
        effects=effects,
        visual_graph=graph.to_dict(),
    )
    recipe.validate()
    return recipe


def _hue_bucket(color_text: str) -> int:
    """Coarse 30-degree hue bucket; -1 for achromatic colors."""
    color = QColor(str(color_text or ""))
    if not color.isValid() or color.alpha() == 0:
        return -1
    hue = int(round(color.hueF() * 12.0)) % 12
    if color.saturationF() < 0.12:
        return -1
    return hue


def typography_signature(graph: VisualDesignGraph) -> tuple[Any, ...]:
    """What the glyphs themselves are made of: fill kind, stroke stack,
    glow/shadow presence. This is the dimension 'typography-led' variants
    must differ in — panel and decoration changes alone do not count."""
    text = graph.text_layer
    fill_kind = str(text.fill.get("type", "solid")).lower()
    stroke_stack = tuple(
        (
            round(float(item.get("width", 0.0) or 0.0)),
            _hue_bucket(str(item.get("color", ""))),
        )
        for item in text.strokes
    )
    glow_on = bool(text.glow.get("enabled") or float(text.glow.get("strength", 0.0) or 0.0) > 0.0)
    shadow_on = bool(text.shadow.get("enabled") or float(text.shadow.get("strength", 0.0) or 0.0) > 0.0)
    return (fill_kind, stroke_stack, glow_on, shadow_on)


def palette_signature(graph: VisualDesignGraph) -> tuple[int, ...]:
    """Hue buckets of the dominant colors (text fill, panel, first accents)."""
    candidates = [
        str(graph.text_layer.fill.get("color", "")),
        str(graph.panel_layer.params.get("color", "")),
        str(graph.panel_layer.params.get("outlineColor", "")),
        *(str(item.params.get("color", "")) for item in graph.decoration_layers[:2]),
    ]
    return tuple(dict.fromkeys(_hue_bucket(item) for item in candidates if _hue_bucket(item) >= 0))


def structural_signature(graph: VisualDesignGraph | Mapping[str, Any]) -> tuple[Any, ...]:
    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    return (
        graph.panel_layer.primitive,
        tuple(item.primitive for item in graph.decoration_layers),
        tuple(item.primitive for item in graph.effect_layers),
        tuple((track.target, track.property) for track in graph.motion_graph.tracks),
        typography_signature(graph),
        palette_signature(graph),
    )


def structural_distance(
    a: VisualDesignGraph | Mapping[str, Any],
    b: VisualDesignGraph | Mapping[str, Any],
) -> int:
    """Count differing structural dimensions between two graphs.

    Dimensions: panel primitive, decoration set, effect set, motion track
    set, typography treatment, palette hue family. Name and font family are
    excluded — those alone are not diversity.
    """
    left = structural_signature(a)
    right = structural_signature(b)
    return sum(1 for x, y in zip(left, right) if x != y)


def validate_structural_variants(
    graphs: Iterable[VisualDesignGraph | Mapping[str, Any]],
) -> tuple[VisualDesignGraph, ...]:
    values = tuple(
        item if isinstance(item, VisualDesignGraph) else VisualDesignGraph.from_dict(item)
        for item in graphs
    )
    if len(values) < 3:
        raise VisualDesignGraphValidationError("A/B/C requires at least three variants")
    for index in range(len(values)):
        for other in range(index + 1, len(values)):
            if structural_distance(values[index], values[other]) < 2:
                raise VisualDesignGraphValidationError(
                    "A/B/C variants must differ in at least two structural "
                    "dimensions (panel, decorations, effects, motion graph, "
                    "typography, palette)"
                )
    palettes = {palette_signature(item) for item in values}
    if len(palettes) == 1 and next(iter(palettes)):
        raise VisualDesignGraphValidationError(
            "A/B/C variants must not share one color family across all three"
        )
    return values


def comic_burst_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="美漫经典爆裂",
        seed=7401,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 72, "weight": 800},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FFFFFF4D"},
                {"position": 1.0, "color": "#FFFF7A00"},
            ]},
            strokes=[
                {"color": "#FF111111", "width": 8, "opacity": 1},
                {"color": "#FFFFFFFF", "width": 2, "opacity": 1},
            ],
            shadow={"enabled": True, "color": "#AA000000", "offset_x": 5, "offset_y": 7, "blur": 3},
            alignment=5,
        ),
        panel_layer=PanelLayer("panel", "COMIC_BURST", {
            "color": "#FFFFD42A", "outlineColor": "#FF111111", "outlineWidth": 6,
            "paddingX": 46, "paddingY": 30, "points": 18,
        }),
        decoration_layers=[
            DecorationLayer("rays", "IMPACT_RAYS", {"color": "#FF111111", "count": 18, "length": 38}, 7401),
            DecorationLayer("dots", "HALFTONE", {"color": "#66000000", "radius": 2.4, "spacing": 11}, 7402),
        ],
        effect_layers=[
            EffectLayer("impact", "IMPACT", {"shakePx": 4, "durationMs": 320, "overshoot": 1.16}, 7403),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("panel", "burst_scale", [
                MotionKeyframe(0, 0.2, "overshoot"), MotionKeyframe(170, 1.16, "overshoot"), MotionKeyframe(280, 1, "ease-out"),
            ]),
            MotionTrack("text", "scale", [
                MotionKeyframe(50, 0.55, "overshoot"), MotionKeyframe(210, 1.18, "overshoot"), MotionKeyframe(320, 1, "ease-out"),
            ]),
            MotionTrack("rays", "ray_scale", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(260, 1, "ease-out"),
            ]),
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(70, 1, "ease-out"),
                MotionKeyframe(2_180, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
        ], stagger_ms=45),
    ).validate()


def glitch_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="故障字幕",
        seed=7411,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 62, "weight": 800},
            fill={"type": "solid", "color": "#FFFFFFFF"},
            strokes=[{"color": "#FF090B10", "width": 5, "opacity": 1}],
            alignment=5,
        ),
        panel_layer=PanelLayer("panel", "RECTANGLE", {
            "color": "#D9090B10", "paddingX": 28, "paddingY": 15,
        }),
        decoration_layers=[
            DecorationLayer("scanlines", "SCANLINES", {"color": "#5520E8FF", "spacing": 5}, 7411),
        ],
        effect_layers=[
            EffectLayer("glitch", "GLITCH", {
                "rgbOffset": 7, "sliceCount": 6, "sliceDisplacement": 13,
                "scanlineOpacity": 0.22, "flicker": 0.16,
            }, 7412),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(70, 1, "step"),
                MotionKeyframe(2_180, 1, "step"), MotionKeyframe(2_320, 0.72, "step"),
                MotionKeyframe(2_400, 0, "step"),
            ]),
            MotionTrack("glitch", "rgb_offset", [
                MotionKeyframe(0, 10, "step"), MotionKeyframe(180, 2, "step"),
                MotionKeyframe(320, 0, "step"), MotionKeyframe(2_400, 0, "step"),
            ]),
            MotionTrack("glitch", "slice_offset", [
                MotionKeyframe(0, 16, "step"), MotionKeyframe(210, 5, "step"),
                MotionKeyframe(360, 0, "step"), MotionKeyframe(2_400, 0, "step"),
            ]),
            MotionTrack("scanlines", "scanline_opacity", [
                MotionKeyframe(0, 0.7, "step"), MotionKeyframe(220, 0.18, "step"),
                MotionKeyframe(2_400, 0.12, "step"),
            ]),
        ]),
    ).validate()


def clean_subtitle_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Clean Subtitle",
        seed=7421,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 56, "weight": 800},
            fill={"type": "solid", "color": "#FFFFFFFF"},
            strokes=[{"color": "#FF000000", "width": 4, "opacity": 1}],
            shadow={"enabled": True, "color": "#99000000", "offset_x": 2, "offset_y": 3, "blur": 3},
            alignment=2,
        ),
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(120, 1, "ease-out"),
                MotionKeyframe(2_250, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
        ]),
    ).validate()


def streamer_gaming_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Streamer Gaming",
        seed=7431,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 64, "weight": 800},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0, "color": "#FFFFFFFF"},
                {"position": 1, "color": "#FFFFD84A"},
            ]},
            strokes=[{"color": "#FF111111", "width": 6, "opacity": 1}],
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "RIBBON", {
            "color": "#E8237A57", "accentColor": "#FFFFD84A", "paddingX": 34,
        }),
        decoration_layers=[
            DecorationLayer("accents", "ACCENT_BARS", {"color": "#FFFFD84A", "count": 3}, 7432),
            DecorationLayer("speed", "SPEED_LINES", {"color": "#AAFFFFFF", "count": 9}, 7433),
        ],
        effect_layers=[
            EffectLayer("impact", "IMPACT", {"shakePx": 2, "durationMs": 220}, 7434),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "x", [
                MotionKeyframe(0, -28, "ease-out-expo"), MotionKeyframe(180, 0, "damped-spring"),
            ]),
            MotionTrack("group", "scale", [
                MotionKeyframe(0, 0.82, "overshoot"), MotionKeyframe(160, 1.08, "spring"),
                MotionKeyframe(280, 1, "damped-spring"),
            ]),
            MotionTrack("group", "rotation", [
                MotionKeyframe(0, -5.5, "spring"), MotionKeyframe(240, 0, "damped-spring"),
            ]),
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(70, 1, "ease-out"),
                MotionKeyframe(2_180, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("accents", "scale", [
                MotionKeyframe(40, 0.2, "overshoot"), MotionKeyframe(240, 1.0, "overshoot"),
            ]),
            MotionTrack("speed", "x", [
                MotionKeyframe(0, -16, "ease-out-expo"), MotionKeyframe(200, 0, "ease-out"),
            ]),
        ], stagger_ms=28),
    ).validate()


def manga_impact_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Manga Impact",
        seed=7441,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 68, "weight": 900},
            fill={"type": "solid", "color": "#FFFFFFFF"},
            strokes=[{"color": "#FF090909", "width": 7, "opacity": 1}],
            alignment=5,
        ),
        panel_layer=PanelLayer("panel", "COMIC_BURST", {
            "color": "#E8F2EEE5", "outlineColor": "#FF090909",
            "outlineWidth": 3, "paddingX": 42, "paddingY": 24,
            "overflow": 0.55,
        }),
        decoration_layers=[
            DecorationLayer("speed", "SPEED_LINES", {
                "color": "#CC090909", "count": 12, "length": 42,
                "overflow": 0.55,
            }, 7442),
            DecorationLayer("shards", "SHARDS", {
                "color": "#AAE3312D", "count": 6, "overflow": 0.45,
            }, 7443),
        ],
        effect_layers=[
            EffectLayer("impact", "IMPACT", {"shakePx": 3, "durationMs": 260}, 7444),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(55, 1, "step"),
                MotionKeyframe(2_190, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("panel", "burst_scale", [
                MotionKeyframe(0, 0.25, "impact"), MotionKeyframe(150, 1.12, "spring"),
                MotionKeyframe(280, 1, "damped-spring"),
            ]),
            MotionTrack("text", "scale", [
                MotionKeyframe(35, 0.72, "impact"), MotionKeyframe(175, 1.14, "spring"),
                MotionKeyframe(300, 1, "damped-spring"),
            ]),
            MotionTrack("speed", "x", [
                MotionKeyframe(0, -24, "ease-out-expo"), MotionKeyframe(220, 0, "ease-out"),
            ]),
            MotionTrack("shards", "scale", [
                MotionKeyframe(80, 0.2, "overshoot"), MotionKeyframe(300, 1, "damped-spring"),
            ]),
            MotionTrack("impact", "shake_x", [
                MotionKeyframe(0, 0, "linear"), MotionKeyframe(120, 3, "impact"),
                MotionKeyframe(260, 0, "damped-spring"),
            ]),
        ], stagger_ms=36),
    ).validate()


def achievement_pop_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Achievement Pop",
        seed=7451,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 58, "weight": 800},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0, "color": "#FFFFFFFF"},
                {"position": 1, "color": "#FFFFE39A"},
            ]},
            strokes=[{"color": "#FF17211D", "width": 5, "opacity": 1}],
            alignment=2,
        ),
        panel_layer=PanelLayer("badge", "BADGE", {
            "color": "#EA237A57", "outlineColor": "#FFFFD84A",
            "outlineWidth": 2, "paddingX": 34, "paddingY": 15,
        }),
        decoration_layers=[
            DecorationLayer("accents", "ACCENT_BARS", {
                "color": "#FFFFD84A", "count": 3,
            }, 7452),
        ],
        effect_layers=[
            EffectLayer("impact", "IMPACT", {"shakePx": 1.5, "durationMs": 180}, 7453),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(80, 1, "ease-out"),
                MotionKeyframe(2_220, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("badge", "scale_x", [
                MotionKeyframe(0, 0.25, "ease-out-expo"), MotionKeyframe(180, 1.05, "spring"),
                MotionKeyframe(290, 1, "damped-spring"),
            ]),
            MotionTrack("text", "scale", [
                MotionKeyframe(85, 0.78, "ease-out-back"), MotionKeyframe(245, 1.08, "spring"),
                MotionKeyframe(340, 1, "damped-spring"),
            ]),
            MotionTrack("accents", "scale", [
                MotionKeyframe(120, 0, "overshoot"), MotionKeyframe(320, 1, "overshoot"),
            ]),
        ], stagger_ms=30),
    ).validate()


def cyber_hud_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Cyber HUD",
        seed=7461,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 54, "weight": 700},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FFEBF8FF"},
                {"position": 1.0, "color": "#FF20E8FF"},
            ]},
            strokes=[{"color": "#FF071018", "width": 4, "opacity": 1}],
            glow={"enabled": True, "color": "#FF20E8FF", "opacity": 0.4, "radius": 6},
            letter_spacing=2.0,
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "TECH_FRAME", {
            "color": "#B4090B10", "outlineColor": "#FF20E8FF", "outlineWidth": 2,
            "paddingX": 30, "paddingY": 14,
        }),
        decoration_layers=[
            DecorationLayer("scan", "SCANLINES", {"color": "#4020E8FF", "spacing": 6}, 7462),
            DecorationLayer("cross", "CROSSHAIR", {"color": "#FF20E8FF", "reach": 26}, 7463),
        ],
        effect_layers=[
            EffectLayer("split", "RGB_SPLIT", {"rgbOffset": 4, "strength": 1.0}, 7464),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(60, 1, "step"),
                MotionKeyframe(2_200, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("text", "tracking", [
                MotionKeyframe(0, 14, "ease-out-expo"), MotionKeyframe(320, 0, "ease-out"),
            ]),
            MotionTrack("text", "char_reveal", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(60, 0.35, "step"),
                MotionKeyframe(180, 0.7, "step"), MotionKeyframe(300, 1.0, "step"),
            ]),
            MotionTrack("scan", "scanline_opacity", [
                MotionKeyframe(0, 0.8, "step"), MotionKeyframe(240, 0.25, "ease-out"),
            ]),
            MotionTrack("cross", "scale", [
                MotionKeyframe(0, 1.4, "ease-out-expo"), MotionKeyframe(260, 1.0, "damped-spring"),
            ]),
            MotionTrack("split", "rgb_offset", [
                MotionKeyframe(0, 12, "step"), MotionKeyframe(200, 4, "ease-out"),
                MotionKeyframe(2_400, 4, "step"),
            ]),
        ], stagger_ms=40),
    ).validate()


def retro_crt_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Retro CRT",
        seed=7471,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 58, "weight": 700},
            fill={"type": "solid", "color": "#FFF2FFC8"},
            strokes=[{"color": "#FF101008", "width": 4, "opacity": 1}],
            glow={"enabled": True, "color": "#AA7CFF6A", "opacity": 0.5, "radius": 9},
            alignment=2,
        ),
        decoration_layers=[
            DecorationLayer("scan", "SCANLINES", {"color": "#557CFF6A", "spacing": 4}, 7472),
        ],
        effect_layers=[
            EffectLayer("split", "RGB_SPLIT", {"rgbOffset": 5, "strength": 1.0}, 7473),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(90, 1, "ease-out"),
                MotionKeyframe(2_240, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("split", "slice_offset", [
                MotionKeyframe(0, 10, "glitch"), MotionKeyframe(240, 0, "ease-out"),
                MotionKeyframe(1_100, 0, "glitch"), MotionKeyframe(1_180, 6, "glitch"),
                MotionKeyframe(1_280, 0, "glitch"), MotionKeyframe(2_400, 0, "glitch"),
            ]),
            MotionTrack("split", "rgb_offset", [
                MotionKeyframe(0, 9, "step"), MotionKeyframe(200, 5, "ease-out"),
                MotionKeyframe(2_400, 5, "step"),
            ]),
            MotionTrack("scan", "scanline_opacity", [
                MotionKeyframe(0, 0.6, "step"), MotionKeyframe(200, 0.3, "ease-out"),
                MotionKeyframe(2_400, 0.3, "step"),
            ]),
        ]),
    ).validate()


def pixel_arcade_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Pixel Arcade",
        seed=7481,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 56, "weight": 800},
            fill={"type": "solid", "color": "#FFFFE93C"},
            strokes=[{"color": "#FF1B0F2B", "width": 6, "opacity": 1},
                      {"color": "#FF4CE0E3", "width": 2, "opacity": 1}],
            alignment=5,
        ),
        panel_layer=PanelLayer("panel", "PIXEL_FRAME", {
            "color": "#D91B0F2B", "outlineColor": "#FF4CE0E3", "outlineWidth": 3,
            "paddingX": 34, "paddingY": 16, "block": 9,
        }),
        decoration_layers=[
            DecorationLayer("tiles", "PIXEL_TILES", {
                "color": "#804CE0E3", "spacing": 18, "size": 5,
            }, 7482),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(50, 1, "step"),
                MotionKeyframe(2_260, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("text", "char_reveal", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(90, 0.2, "step"),
                MotionKeyframe(200, 0.45, "step"), MotionKeyframe(320, 0.7, "step"),
                MotionKeyframe(440, 1.0, "step"),
            ]),
            MotionTrack("panel", "scale_x", [
                MotionKeyframe(0, 0.3, "step"), MotionKeyframe(120, 1.0, "step"),
            ]),
            MotionTrack("panel", "scale_y", [
                MotionKeyframe(0, 0.2, "step"), MotionKeyframe(160, 1.0, "step"),
            ]),
            MotionTrack("tiles", "opacity", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(260, 0.8, "step"),
            ]),
        ], stagger_ms=45),
    ).validate()


def anime_variety_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Anime Variety",
        seed=7491,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 62, "weight": 900},
            fill={"type": "solid", "color": "#FFFFF6F6"},
            strokes=[{"color": "#FFE8386D", "width": 7, "opacity": 1}],
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "MARKER", {
            "color": "#66FFD84A", "skew": 8, "paddingX": 26, "paddingY": 8,
        }),
        decoration_layers=[
            DecorationLayer("glyphs", "FLOAT_GLYPHS", {
                "color": "#FFF2EE6D", "count": 6, "symbols": "✦★●",
            }, 7492),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(80, 1, "ease-out"),
                MotionKeyframe(2_220, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("group", "scale", [
                MotionKeyframe(0, 0.6, "ease-out-back"), MotionKeyframe(200, 1.12, "spring"),
                MotionKeyframe(340, 1, "damped-spring"),
            ]),
            MotionTrack("group", "rotation", [
                MotionKeyframe(0, -4, "spring"), MotionKeyframe(240, 0, "damped-spring"),
            ]),
            MotionTrack("text", "y", [
                MotionKeyframe(0, 26, "ease-out-back"), MotionKeyframe(220, -6, "spring"),
                MotionKeyframe(360, 0, "damped-spring"),
            ]),
            MotionTrack("glyphs", "y", [
                MotionKeyframe(120, 18, "ease-out"), MotionKeyframe(420, 0, "damped-spring"),
            ]),
            MotionTrack("glyphs", "opacity", [
                MotionKeyframe(140, 0, "ease-out"), MotionKeyframe(380, 1, "ease-out"),
            ]),
        ], stagger_ms=36),
    ).validate()


def clean_premium_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="Clean Premium",
        seed=7501,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 50, "weight": 600},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FFFFFFFF"},
                {"position": 1.0, "color": "#FFC9D6E8"},
            ]},
            strokes=[],
            shadow={"enabled": True, "color": "#66000000", "offset_x": 1, "offset_y": 2, "blur": 2},
            letter_spacing=3.0,
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "NONE", {}),
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(260, 1, "ease-out"),
                MotionKeyframe(2_260, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("text", "tracking", [
                MotionKeyframe(0, 8, "ease-out"), MotionKeyframe(420, 0, "ease-out"),
            ]),
            MotionTrack("text", "char_reveal", [
                MotionKeyframe(0, 0.0, "ease-out"), MotionKeyframe(200, 0.5, "ease-out"),
                MotionKeyframe(460, 1.0, "ease-out"),
            ]),
            MotionTrack("text", "y", [
                MotionKeyframe(0, 8, "ease-out"), MotionKeyframe(360, 0, "ease-out"),
            ]),
        ]),
    ).validate()


def industrial_brass_hud_graph() -> VisualDesignGraph:
    """Steampunk A: Industrial Brass HUD — brass gradient glyphs on an iron plate."""

    return VisualDesignGraph(
        name="Industrial Brass HUD",
        seed=7521,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 54, "weight": 800},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FFFFE9B8"},
                {"position": 0.45, "color": "#FFD9A441"},
                {"position": 1.0, "color": "#FF8A5A19"},
            ]},
            strokes=[
                {"color": "#FF241505", "width": 7, "opacity": 1},
                {"color": "#FFFFD98C", "width": 2, "opacity": 1},
            ],
            glow={"enabled": True, "color": "#73FFC46A", "opacity": 0.35, "radius": 10},
            shadow={"enabled": True, "color": "#96000000", "offset_x": 2, "offset_y": 3, "blur": 3},
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "MECHANICAL_PLATE", {
            "color": "#E62E241A", "outlineColor": "#FFC9971F", "outlineWidth": 3,
            "paddingX": 40, "paddingY": 20, "cornerRadius": 8,
        }),
        decoration_layers=[
            DecorationLayer("rivets", "RIVETS", {
                "color": "#FFD9A441", "count": 6, "size": 5,
            }, 7522),
            DecorationLayer("gauge", "GAUGE", {
                "color": "#FFC9971F", "needleColor": "#FFFFE9B8", "size": 54,
            }, 7523),
            DecorationLayer("pipes", "PIPES", {
                "color": "#C08A5A19", "count": 2, "thickness": 6,
            }, 7524),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(120, 1, "ease-out"),
                MotionKeyframe(2_280, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("panel", "scale_x", [
                MotionKeyframe(0, 0.35, "ease-out-expo"), MotionKeyframe(180, 1, "ease-out-expo"),
            ]),
            MotionTrack("panel", "opacity", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(140, 1, "ease-out"),
            ]),
            MotionTrack("text", "mask_reveal", [
                MotionKeyframe(120, 0.0, "ease-out"), MotionKeyframe(460, 1.0, "ease-out"),
            ]),
            MotionTrack("rivets", "opacity", [
                MotionKeyframe(200, 0.0, "step"), MotionKeyframe(340, 1.0, "damped-spring"),
            ]),
            MotionTrack("gauge", "rotation", [
                MotionKeyframe(160, -38, "damped-spring"), MotionKeyframe(520, 4, "damped-spring"),
                MotionKeyframe(2_400, 4, "step"),
            ]),
            MotionTrack("pipes", "opacity", [
                MotionKeyframe(260, 0.0, "step"), MotionKeyframe(420, 0.9, "ease-out"),
            ]),
        ], stagger_ms=60),
    ).validate()


def victorian_mechanical_graph() -> VisualDesignGraph:
    """Steampunk B: Victorian Mechanical Plate — copper serif plate with gears."""

    return VisualDesignGraph(
        name="Victorian Mechanical Plate",
        seed=7531,
        text_layer=TextLayer(
            font={"family": "Source Han Serif CN", "size": 52, "weight": 600},
            fill={"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FFFFE2C0"},
                {"position": 0.5, "color": "#FFB87333"},
                {"position": 1.0, "color": "#FF7A4A1D"},
            ]},
            strokes=[
                {"color": "#FF201008", "width": 6, "opacity": 1},
                {"color": "#FFF6E7CE", "width": 2, "opacity": 1},
            ],
            shadow={"enabled": True, "color": "#8C000000", "offset_x": 2, "offset_y": 4, "blur": 4},
            letter_spacing=2.0,
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "MECHANICAL_PLATE", {
            "color": "#E6391F0F", "outlineColor": "#FFB87333", "outlineWidth": 4,
            "paddingX": 46, "paddingY": 24, "cornerRadius": 4, "ornate": True,
        }),
        decoration_layers=[
            DecorationLayer("gearL", "GEARS", {
                "color": "#FFC9971F", "count": 2, "size": 40, "side": "left",
            }, 7532),
            DecorationLayer("gearR", "GEARS", {
                "color": "#FF9C6B1E", "count": 1, "size": 52, "side": "right",
            }, 7533),
            DecorationLayer("steam", "STEAM", {
                "color": "#66E8DCC8", "count": 5, "size": 26,
            }, 7534),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "ease-out"), MotionKeyframe(160, 1, "ease-out"),
                MotionKeyframe(2_300, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("panel", "y", [
                MotionKeyframe(0, 14, "ease-out"), MotionKeyframe(320, 0, "damped-spring"),
            ]),
            MotionTrack("panel", "opacity", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(180, 1, "ease-out"),
            ]),
            MotionTrack("gearL", "rotation", [
                MotionKeyframe(0, 0, "linear"), MotionKeyframe(2_400, 140, "linear"),
            ], post_behavior="RESET"),
            MotionTrack("gearR", "rotation", [
                MotionKeyframe(0, 0, "linear"), MotionKeyframe(2_400, -95, "linear"),
            ], post_behavior="RESET"),
            MotionTrack("text", "char_reveal", [
                MotionKeyframe(180, 0.0, "step"), MotionKeyframe(560, 1.0, "ease-out"),
            ]),
            MotionTrack("steam", "opacity", [
                MotionKeyframe(300, 0.0, "step"), MotionKeyframe(640, 0.55, "ease-in-out"),
                MotionKeyframe(1_500, 0.3, "ease-in-out"), MotionKeyframe(2_400, 0.45, "ease-in-out"),
            ]),
            MotionTrack("steam", "y", [
                MotionKeyframe(300, 10, "ease-in-out"), MotionKeyframe(2_400, -18, "ease-in-out"),
            ]),
        ], stagger_ms=70),
    ).validate()


def steam_gauge_graph() -> VisualDesignGraph:
    """Steampunk C: Steam Gauge Typography — needle sweep behind aged gold type."""

    return VisualDesignGraph(
        name="Steam Gauge Typography",
        seed=7541,
        text_layer=TextLayer(
            font={"family": "Source Han Sans CN", "size": 50, "weight": 700},
            fill={"type": "radial-gradient", "stops": [
                {"position": 0.0, "color": "#FFFFF3D6"},
                {"position": 0.6, "color": "#FFE0B25C"},
                {"position": 1.0, "color": "#FFA06B22"},
            ]},
            strokes=[
                {"color": "#FF1C1206", "width": 5, "opacity": 1},
                {"color": "#FFD9A441", "width": 2, "opacity": 1},
            ],
            glow={"enabled": True, "color": "#59FFC46A", "opacity": 0.4, "radius": 12},
            alignment=2,
        ),
        panel_layer=PanelLayer("panel", "LOWER_THIRD", {
            "color": "#D9331808", "outlineColor": "#FFD9A441", "outlineWidth": 3,
            "paddingX": 38, "paddingY": 18, "skew": -6,
        }),
        decoration_layers=[
            DecorationLayer("dial", "GAUGE", {
                "color": "#FFC9971F", "needleColor": "#FFFFF3D6", "size": 96, "ticks": True,
            }, 7542),
            DecorationLayer("rivets", "RIVETS", {
                "color": "#FFE0B25C", "count": 8, "size": 4,
            }, 7543),
            DecorationLayer("steam", "STEAM", {
                "color": "#4DE8DCC8", "count": 4, "size": 30,
            }, 7544),
        ],
        motion_graph=MotionGraph(2_400, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0, "step"), MotionKeyframe(140, 1, "ease-out"),
                MotionKeyframe(2_300, 1, "ease-in"), MotionKeyframe(2_400, 0, "ease-in"),
            ]),
            MotionTrack("dial", "rotation", [
                MotionKeyframe(0, -95, "damped-spring"), MotionKeyframe(620, 14, "damped-spring"),
                MotionKeyframe(2_400, 14, "step"),
            ]),
            MotionTrack("dial", "opacity", [
                MotionKeyframe(0, 0.0, "step"), MotionKeyframe(200, 0.9, "ease-out"),
            ]),
            MotionTrack("panel", "scale_x", [
                MotionKeyframe(80, 0.2, "ease-out-expo"), MotionKeyframe(300, 1, "ease-out-expo"),
            ]),
            MotionTrack("text", "mask_reveal", [
                MotionKeyframe(240, 0.0, "ease-out"), MotionKeyframe(620, 1.0, "ease-out"),
            ]),
            MotionTrack("rivets", "opacity", [
                MotionKeyframe(320, 0.0, "step"), MotionKeyframe(480, 1.0, "damped-spring"),
            ]),
            MotionTrack("steam", "opacity", [
                MotionKeyframe(400, 0.0, "step"), MotionKeyframe(760, 0.4, "ease-in-out"),
            ]),
        ], stagger_ms=55),
    ).validate()


GOLDEN_VISUAL_GRAPHS = {
    "american_comic_burst": comic_burst_graph,
    "manga_impact": manga_impact_graph,
    "crt_glitch": glitch_graph,
    "streamer_pop": streamer_gaming_graph,
    "achievement": achievement_pop_graph,
    "clean_editorial": clean_subtitle_graph,
    "cyber_hud": cyber_hud_graph,
    "retro_crt": retro_crt_graph,
    "pixel_arcade": pixel_arcade_graph,
    "anime_variety": anime_variety_graph,
    "clean_premium": clean_premium_graph,
    "industrial_brass_hud": industrial_brass_hud_graph,
    "victorian_mechanical": victorian_mechanical_graph,
    "steam_gauge": steam_gauge_graph,
}


@dataclass(frozen=True)
class LiveSceneSample:
    time_ms: int
    values: Mapping[str, Mapping[str, float]]

    def value(self, target: str, property_name: str, default: float = 0.0) -> float:
        return float(self.values.get(target, {}).get(property_name, default))


def _ease(progress: float, easing: str) -> float:
    p = max(0.0, min(1.0, progress))
    kind = str(easing or "linear").lower().replace("_", "-")
    if kind in {"step", "glitch"}:
        return 0.0 if p < 1.0 else 1.0
    if kind == "ease-in":
        return p * p
    if kind in {"easeoutexpo", "ease-out-expo"}:
        return 1.0 if p >= 1.0 else 1.0 - pow(2.0, -10.0 * p)
    if kind == "ease-out":
        return 1.0 - (1.0 - p) ** 2
    if kind in {"ease-in-out", "easeinoutcubic", "ease-in-out-cubic"}:
        return 4 * p * p * p if p < 0.5 else 1 - pow(-2 * p + 2, 3) / 2
    if kind in {"overshoot", "easeoutback", "ease-out-back", "impact", "impactcurve"}:
        c1 = 1.70158 if "back" in kind or kind == "overshoot" else 2.075
        c3 = c1 + 1
        return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2
    if kind in {"spring", "dampedspring", "damped-spring"}:
        decay = math.exp(-6.0 * p)
        return 1.0 - decay * math.cos(p * 12.0)
    return p


@dataclass(frozen=True)
class CompiledLiveScene:
    graph: VisualDesignGraph
    tracks: tuple[tuple[str, str, tuple[MotionKeyframe, ...], str], ...]
    compile_ms: float
    graph_hash: str

    @classmethod
    def compile(
        cls,
        graph: VisualDesignGraph | Mapping[str, Any],
        *,
        cue_duration_ms: int | None = None,
    ) -> "CompiledLiveScene":
        started = perf_counter()
        if not isinstance(graph, VisualDesignGraph):
            graph = VisualDesignGraph.from_dict(graph)
        if cue_duration_ms is not None:
            # The single cue-binding owner: AI cards, live playback, fidelity,
            # and export all compile through here, so every consumer samples a
            # graph whose exit is anchored to the real cue end.
            graph = normalize_motion_graph_to_cue(graph, cue_duration_ms)
        else:
            graph.validate()
        tracks = tuple(
            (
                track.target, track.property, tuple(track.keyframes),
                track.post_behavior,
            )
            for track in graph.motion_graph.tracks
        )
        return cls(
            copy.deepcopy(graph), tracks,
            (perf_counter() - started) * 1000.0, graph.stable_hash(),
        )

    def sample(self, time_ms: int | float) -> LiveSceneSample:
        duration = self.graph.motion_graph.duration_ms
        current = max(0, min(duration, int(time_ms)))
        values: dict[str, dict[str, float]] = {
            "group": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
        }
        for target, property_name, frames, post_behavior in self.tracks:
            default_value = _motion_property_default(property_name)
            if current < frames[0].time_ms:
                # Before this track's window: another track sharing the same
                # (target, property) — an entrance/exit split — may already
                # own the value. Do not clobber it with the property default.
                continue
            elif current == frames[0].time_ms:
                sampled = frames[0].value
            elif current >= frames[-1].time_ms:
                sampled = (
                    default_value
                    if current > frames[-1].time_ms and post_behavior == "RESET"
                    else frames[-1].value
                )
            else:
                left, right = frames[0], frames[-1]
                for index in range(1, len(frames)):
                    if current <= frames[index].time_ms:
                        left, right = frames[index - 1], frames[index]
                        break
                span = max(1, right.time_ms - left.time_ms)
                progress = _ease((current - left.time_ms) / span, right.easing)
                sampled = left.value + (right.value - left.value) * progress
            existing = values.get(target, {}).get(property_name)
            if (
                existing is not None
                and property_name == "opacity"
                and existing != sampled
            ):
                # Overlapping entrance/hold and exit tracks combine by
                # whichever is more transparent.
                sampled = min(existing, sampled)
            values.setdefault(target, {})[property_name] = float(sampled)

        # Deterministic effect modulation; no frame-time randomness is used.
        for effect in self.graph.effect_layers:
            target = values.setdefault(effect.id, {})
            if effect.primitive == "GLITCH":
                phase = (current + effect.seed * 17) % 1_700
                active = phase < 150 or current < 320
                if active:
                    pulse = math.sin((current + effect.seed) * 0.071)
                    target.setdefault("rgb_offset", float(effect.params.get("rgbOffset", 6)) * abs(pulse))
                    target.setdefault("slice_offset", float(effect.params.get("sliceDisplacement", 10)) * pulse)
                    target.setdefault("flicker", float(effect.params.get("flicker", 0.14)) * abs(math.sin(current * 0.113)))
                else:
                    target.setdefault("rgb_offset", 0.0)
                    target.setdefault("slice_offset", 0.0)
                    target.setdefault("flicker", 0.0)
            elif effect.primitive == "RGB_SPLIT":
                # Constant chromatic aberration; a rgb_offset motion track on
                # the same layer overrides the static amount.
                target.setdefault(
                    "rgb_offset",
                    float(effect.params.get("rgbOffset", 4)) * (
                        float(effect.params.get("strength", 1)) or 1.0
                    ),
                )
            elif effect.primitive == "IMPACT":
                effect_duration = max(1, int(effect.params.get("durationMs", 280)))
                if current < effect_duration:
                    decay = 1.0 - current / effect_duration
                    shake = float(effect.params.get("shakePx", 3)) * decay
                    target.setdefault("shake_x", math.sin((current + effect.seed) * 0.21) * shake)
                    target.setdefault("shake_y", math.cos((current + effect.seed) * 0.27) * shake)
        return LiveSceneSample(current, values)


def compile_live_scene(
    graph: VisualDesignGraph | Mapping[str, Any],
    *,
    cue_duration_ms: int | None = None,
) -> CompiledLiveScene:
    """Single compiler used by AI cards, Studio playback, Fidelity, and export."""

    return CompiledLiveScene.compile(graph, cue_duration_ms=cue_duration_ms)


# Compiled scenes are immutable and cheap to sample but not free to build
# (validation + cue normalization + deep copy). Re-entering the same cue —
# replay, seek-back, ownership handoff — hits this memo instead.
_COMPILED_SCENE_MEMO_MAX = 16
_COMPILED_SCENE_MEMO: dict[tuple[str, int], CompiledLiveScene] = {}


def compile_live_scene_cached(
    graph: VisualDesignGraph | Mapping[str, Any],
    *,
    cue_duration_ms: int | None = None,
) -> CompiledLiveScene:
    key = (
        hashlib.sha256(
            json.dumps(
                graph if isinstance(graph, Mapping) else graph.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
        int(cue_duration_ms or 0),
    )
    scene = _COMPILED_SCENE_MEMO.get(key)
    if scene is not None:
        return scene
    scene = compile_live_scene(graph, cue_duration_ms=cue_duration_ms)
    if len(_COMPILED_SCENE_MEMO) >= _COMPILED_SCENE_MEMO_MAX:
        _COMPILED_SCENE_MEMO.clear()
    _COMPILED_SCENE_MEMO[key] = scene
    return scene


def _motion_property_default(property_name: str) -> float:
    return 1.0 if property_name in UNIT_DEFAULT_PROPERTIES else 0.0


@dataclass(frozen=True)
class MotionPhases:
    entrance_start_ms: int
    entrance_end_ms: int
    hold_start_ms: int
    hold_end_ms: int
    exit_start_ms: int
    exit_end_ms: int


def motion_phases(graph: VisualDesignGraph | Mapping[str, Any]) -> MotionPhases:
    """Infer stable cue phases from the generic trusted MotionGraph."""

    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    duration = max(1, graph.motion_graph.duration_ms)
    early_limit = round(duration * 0.40)
    early = [
        frame.time_ms for track in graph.motion_graph.tracks
        for frame in track.keyframes if frame.time_ms <= early_limit
    ]
    exit_starts = [
        track.keyframes[-2].time_ms
        for track in graph.motion_graph.tracks
        if len(track.keyframes) >= 2
        and track.keyframes[-1].time_ms >= round(duration * 0.90)
        and track.keyframes[-2].time_ms >= round(duration * 0.55)
    ]
    entrance_end = min(early_limit, max(early, default=0))
    exit_start = min(exit_starts, default=duration)
    exit_start = max(entrance_end, exit_start)
    return MotionPhases(
        0, entrance_end, entrance_end, exit_start,
        exit_start, duration,
    )


CUE_PHASE_BEFORE = "BEFORE_CUE"
CUE_PHASE_ENTRANCE = "ENTRANCE"
CUE_PHASE_HOLD = "HOLD"
CUE_PHASE_EXIT = "EXIT"
CUE_PHASE_AFTER = "AFTER_CUE"


def cue_motion_phase(
    relative_ms: int,
    *,
    entrance_end_ms: int,
    exit_start_ms: int,
    cue_duration_ms: int,
) -> str:
    """Cue motion state machine: only BEFORE_CUE and AFTER_CUE may hide."""

    duration = max(1, int(cue_duration_ms))
    moment = int(relative_ms)
    if moment < 0:
        return CUE_PHASE_BEFORE
    if moment >= duration:
        return CUE_PHASE_AFTER
    if moment < max(0, int(entrance_end_ms)):
        return CUE_PHASE_ENTRANCE
    if moment < max(0, int(exit_start_ms)):
        return CUE_PHASE_HOLD
    return CUE_PHASE_EXIT


def normalize_motion_graph_to_cue(
    graph: VisualDesignGraph | Mapping[str, Any],
    cue_duration_ms: int,
) -> VisualDesignGraph:
    """Map a design-intent motion graph onto its real cue span.

    A stored graph is cue-relative design intent: its ``durationMs`` is the
    nominal design duration and rarely equals the actual cue. This single
    owner maps the graph onto the cue with ENTRANCE -> HOLD -> EXIT
    semantics:

    * the entrance keeps its designed timing (capped at 60% of the cue),
    * a declared exit (or any tail opacity fade-out) is anchored to the cue
      end so the scene is never hidden before the cue is over,
    * the hold stretches to fill the remainder,
    * a graph without an exit holds its readable value until ``cue_duration``.

    "Entrance completed" must mean HOLD, never "element hidden".
    """

    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    cue_ms = max(120, int(cue_duration_ms or 0) or graph.motion_graph.duration_ms)
    normalized = copy.deepcopy(graph)
    motion = normalized.motion_graph
    if not motion.tracks:
        motion.duration_ms = cue_ms
        normalized.validate()
        return normalized

    source_ms = max(1, motion.duration_ms)
    phases = motion_phases(graph)
    entrance_end = min(phases.entrance_end_ms, source_ms - 1)
    exit_start = phases.exit_start_ms
    # Any tail opacity fade-out is an exit even when it sits earlier than the
    # 55%/90% heuristics in motion_phases; holding a faded-out value would
    # blank the rest of the cue (the applied-AI-disappears bug).
    for track in motion.tracks:
        if track.property == "opacity" and len(track.keyframes) >= 2:
            tail = track.keyframes[-1]
            if tail.value < 0.5:
                exit_start = min(exit_start, track.keyframes[-2].time_ms)
    exit_start = max(entrance_end, min(exit_start, source_ms))

    entrance_len = entrance_end
    exit_len = source_ms - exit_start
    cap = max(60, int(cue_ms * 0.6))
    new_entrance = min(entrance_len, cap)
    new_exit = min(exit_len, cap)
    if new_entrance + new_exit > cue_ms:
        new_entrance = min(new_entrance, cue_ms // 2)
        new_exit = min(new_exit, cue_ms - new_entrance)
    hold_end = cue_ms - new_exit

    def map_time(moment: int) -> int:
        if moment <= entrance_end:
            if entrance_end <= 0:
                return min(moment, new_entrance)
            return round(moment * (new_entrance / entrance_end))
        if moment <= exit_start:
            span = max(1, exit_start - entrance_end)
            out_span = max(0, hold_end - new_entrance)
            return new_entrance + round((moment - entrance_end) * (out_span / span))
        span = max(1, source_ms - exit_start)
        return hold_end + round((moment - exit_start) * (new_exit / span))

    for track in motion.tracks:
        track.keyframes = sorted(
            (
                MotionKeyframe(
                    min(cue_ms, max(0, map_time(frame.time_ms))),
                    frame.value,
                    frame.easing,
                )
                for frame in track.keyframes
            ),
            key=lambda frame: frame.time_ms,
        )
    motion.duration_ms = cue_ms
    normalized.validate()
    return normalized


def effect_signature(graph: VisualDesignGraph | Mapping[str, Any]) -> tuple[Any, ...]:
    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    animated = tuple(sorted({
        f"{track.target}:{track.property}" for track in graph.motion_graph.tracks
    }))
    return (
        graph.panel_layer.primitive,
        tuple(item.primitive for item in graph.decoration_layers),
        tuple(item.primitive for item in graph.effect_layers),
        animated,
        effect_family(graph),
        int(graph.motion_graph.duration_ms),
    )


def is_weak_motion_graph(graph: VisualDesignGraph | Mapping[str, Any]) -> bool:
    """True when a named dramatic family is actually just scale/slide/fade."""

    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    properties = {track.property for track in graph.motion_graph.tracks}
    layer_ids = {item.id for item in graph.decoration_layers} | {
        item.id for item in graph.effect_layers
    } | {graph.panel_layer.id}
    animates_layers = any(track.target in layer_ids for track in graph.motion_graph.tracks)
    cheap_only = bool(properties) and properties <= CHEAP_MOTION_PROPERTIES
    name = str(graph.name or "").casefold()
    wants_effect = any(
        token in name
        for token in ("glitch", "故障", "burst", "爆裂", "comic", "gaming", "impact", "punch")
    )
    if wants_effect and not graph.effect_layers and not animates_layers:
        return True
    if cheap_only and not graph.effect_layers and not animates_layers:
        return True
    return False


def layer_coordinate_space(layer: Any) -> str:
    """Resolve the coordinate contract for one VisualDesignGraph layer.

    Text lives in the subtitle content box. Panel, decoration and effect
    layers default to that same subtitle-local box. A Transform then maps
    the whole composition onto the video canvas. Width/overflow percentages
    never mean "percent of the video frame" unless coordinateSpace is
    explicitly video-canvas.
    """

    if isinstance(layer, TextLayer):
        return COORDINATE_SPACE_TEXT
    params = layer.params if isinstance(getattr(layer, "params", None), Mapping) else {}
    declared = str(params.get("coordinateSpace") or params.get("coordinate_space") or "").strip()
    if declared in COORDINATE_SPACES:
        return declared
    return COORDINATE_SPACE_SUBTITLE_LOCAL


def visual_composition_bounds(
    text_bounds: tuple[float, float, float, float],
    graph: VisualDesignGraph | Mapping[str, Any],
    *,
    type_scale: float = 1.0,
) -> tuple[float, float, float, float]:
    """Expand text bounds by explicit overflow only. Never to the video frame."""

    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    x, y, width, height = (float(item) for item in text_bounds)
    padding_x = 0.0
    padding_y = 0.0
    layers = [graph.panel_layer, *graph.decoration_layers, *graph.effect_layers]
    for layer in layers:
        if layer_coordinate_space(layer) == COORDINATE_SPACE_VIDEO_CANVAS:
            continue
        params = layer.params if isinstance(getattr(layer, "params", None), Mapping) else {}
        overflow_x = 0.35
        overflow_y = 0.35
        for key in ("overflowX", "overflow_x", "overflow"):
            if key in params:
                overflow_x = max(overflow_x, min(1.2, float(params.get(key) or 0)))
        for key in ("overflowY", "overflow_y", "overflow"):
            if key in params:
                overflow_y = max(overflow_y, min(1.2, float(params.get(key) or 0)))
        padding_x = max(
            padding_x,
            min(width * overflow_x, float(params.get("paddingX", params.get("padding_x", 20)) or 20) * type_scale),
        )
        padding_y = max(
            padding_y,
            min(height * overflow_y, float(params.get("paddingY", params.get("padding_y", 12)) or 12) * type_scale),
        )
    return (x - padding_x, y - padding_y, width + padding_x * 2, height + padding_y * 2)


def effect_family(graph: VisualDesignGraph | Mapping[str, Any]) -> str:
    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    name = str(graph.name or "").casefold()
    primitives = {item.primitive for item in graph.effect_layers} | {
        item.primitive for item in graph.decoration_layers
    }
    primitives.add(graph.panel_layer.primitive)
    if "GLITCH" in primitives or any(token in name for token in ("glitch", "故障", "signal")):
        return "GLITCH_SIGNAL_LOSS" if "signal" in name else "GLITCH_DIGITAL"
    if "COMIC_BURST" in primitives or "IMPACT_RAYS" in primitives or any(token in name for token in ("burst", "comic", "爆裂", "美漫")):
        return "COMIC_BURST"
    if any(token in name for token in ("stream", "gaming", "游戏")):
        return "STREAMER_POP"
    if "IMPACT" in primitives:
        return "PUNCH" if any(token in name for token in ("punch", "slam")) else "IMPACT"
    return "IMPACT" if graph.motion_graph.tracks else ""


def readability_issues(graph: VisualDesignGraph | Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(graph, VisualDesignGraph):
        graph = VisualDesignGraph.from_dict(graph)
    graph.validate()
    issues: list[str] = []
    duration = max(1, int(graph.motion_graph.duration_ms or 1))
    glitch = next((item for item in graph.effect_layers if item.primitive == "GLITCH"), None)
    if glitch is not None:
        flicker = float(glitch.params.get("flicker", 0) or 0)
        rgb = float(glitch.params.get("rgbOffset", 0) or 0)
        if flicker > 0.45:
            issues.append("glitch flicker covers too much of the hold")
        if rgb > 18:
            issues.append("glitch RGB split is too wide for glyph readability")
        if not graph.motion_graph.tracks:
            issues.append("glitch has no recovery/hold structure")
        rgb_track = next(
            (track for track in graph.motion_graph.tracks if track.property == "rgb_offset"),
            None,
        )
        if rgb_track is not None and all(abs(frame.value) > 2.0 for frame in rgb_track.keyframes):
            issues.append("glitch never recovers to a readable hold")
    times = [frame.time_ms for track in graph.motion_graph.tracks for frame in track.keyframes]
    if times and min(times) == 0 and max(times) > duration * 0.42 and duration > 600:
        early = [time for time in times if time <= duration * 0.5]
        if early and max(early) > duration * 0.4:
            issues.append("entrance consumes too much of the readable hold")
    panel = graph.panel_layer
    if panel.primitive != "NONE":
        color = str(panel.params.get("color") or panel.params.get("fill") or "")
        if len(color) == 9:
            alpha = int(color[1:3], 16) / 255.0
            if alpha < 0.18:
                issues.append("panel contrast is too low for readable glyphs")
    # Design Critic: decoration must orbit the text, not bury it.
    high_energy = sum(
        1 for item in graph.decoration_layers
        if item.primitive in {"IMPACT_RAYS", "SPEED_LINES", "SHARDS", "PIXEL_TILES", "FLOAT_GLYPHS", "INK_SPLAT"}
    )
    if high_energy > 3:
        issues.append("too many competing decorations bury the glyphs")
    if len(graph.decoration_layers) + len(graph.effect_layers) > 6:
        issues.append("effect stack is too dense for a subtitle cue")
    max_overflow = max(
        (
            float(item.params.get("overflow", 0) or 0)
            for item in graph.decoration_layers
        ),
        default=0.0,
    )
    if max_overflow > 0.9:
        issues.append("decoration overflow covers too much of the frame")
    return tuple(issues)


def repair_weak_motion_graph(graph: VisualDesignGraph) -> VisualDesignGraph:
    """One deterministic repair pass for WEAK_MOTION_GRAPH."""

    graph.validate()
    if not is_weak_motion_graph(graph):
        return graph
    name = str(graph.name or "").casefold()
    duration = max(900, int(graph.motion_graph.duration_ms or 2_400))
    tracks = list(graph.motion_graph.tracks)
    if any(token in name for token in ("glitch", "故障")):
        if not any(item.primitive == "GLITCH" for item in graph.effect_layers):
            graph.effect_layers.append(EffectLayer(
                "glitch", "GLITCH",
                {"rgbOffset": 7, "sliceCount": 6, "sliceDisplacement": 12, "flicker": 0.14},
                graph.seed + 17,
            ))
        glitch_id = next(item.id for item in graph.effect_layers if item.primitive == "GLITCH")
        tracks.extend([
            MotionTrack(glitch_id, "rgb_offset", [
                MotionKeyframe(0, 9, "step"), MotionKeyframe(160, 2, "step"),
                MotionKeyframe(280, 0, "step"), MotionKeyframe(duration, 0, "step"),
            ]),
            MotionTrack(glitch_id, "slice_offset", [
                MotionKeyframe(0, 14, "step"), MotionKeyframe(180, 4, "step"),
                MotionKeyframe(320, 0, "step"), MotionKeyframe(duration, 0, "step"),
            ]),
        ])
    elif any(token in name for token in ("burst", "comic", "爆裂", "美漫")):
        panel_id = graph.panel_layer.id
        tracks.extend([
            MotionTrack(panel_id, "burst_scale", [
                MotionKeyframe(0, 0.18, "overshoot"),
                MotionKeyframe(160, 1.14, "overshoot"),
                MotionKeyframe(280, 1.0, "ease-out"),
            ]),
        ])
        if graph.decoration_layers:
            tracks.append(MotionTrack(graph.decoration_layers[0].id, "ray_scale", [
                MotionKeyframe(0, 0.0, "ease-out"),
                MotionKeyframe(240, 1.0, "ease-out"),
            ]))
    else:
        tracks.extend([
            MotionTrack("group", "scale", [
                MotionKeyframe(0, 0.86, "overshoot"),
                MotionKeyframe(140, 1.08, "overshoot"),
                MotionKeyframe(240, 1.0, "ease-out"),
            ]),
        ])
    graph.motion_graph.tracks = tracks
    graph.motion_graph.duration_ms = duration
    graph.validate()
    return graph


__all__ = [
    "CompiledLiveScene", "DECORATION_PRIMITIVES", "EFFECT_PRIMITIVES",
    "EFFECT_FAMILIES",
    "COORDINATE_SPACE_SUBTITLE_LOCAL", "COORDINATE_SPACE_TEXT",
    "COORDINATE_SPACE_VIDEO_CANVAS",
    "compile_live_scene", "motion_phases",
    "cue_motion_phase", "normalize_motion_graph_to_cue", "structural_distance",
    "effect_family", "effect_signature", "is_weak_motion_graph",
    "layer_coordinate_space", "readability_issues",
    "repair_weak_motion_graph", "visual_composition_bounds",
    "EffectLayer", "GOLDEN_VISUAL_GRAPHS", "GRAPH_SCHEMA", "GRAPH_VERSION",
    "LiveSceneSample", "MotionGraph", "MotionKeyframe", "MotionPhases", "MotionTrack",
    "MOTION_POST_BEHAVIORS",
    "PANEL_PRIMITIVES", "PanelLayer", "DecorationLayer", "TextLayer",
    "VisualDesignGraph", "VisualDesignGraphValidationError", "achievement_pop_graph",
    "clean_subtitle_graph",
    "comic_burst_graph", "glitch_graph", "graph_from_style_recipe",
    "manga_impact_graph", "streamer_gaming_graph", "structural_signature", "style_recipe_from_graph",
    "validate_structural_variants",
]
