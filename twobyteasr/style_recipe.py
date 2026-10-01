"""Stable style-recipe boundary shared by UI, AI design, and renderers."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .effect_dsl import EFFECT_TYPES, TEXT_EFFECT_TYPES, builtin_effects, validate_effect
from .studio_project import SubtitleStyle
from .visual_runtime import VisualRenderer, renderer_capability_gaps


RECIPE_FIELDS = (
    "name", "engine", "typography", "layout", "colors", "outline",
    "background", "motion", "wordHighlight", "effects", "ass", "visualGraph",
    "webTheme",
)
# Gradient / advanced visual fields are intentionally not in NATIVE_SECTION_KEYS.
# When present they force engine=remotion (advanced).
NATIVE_SECTION_KEYS = {
    "typography": {
        "fontFamily", "fontSize", "bold", "italic", "underline", "spacing",
        "scaleX", "scaleY", "fontWeight", "fontStyleName", "fontFile", "fontFaceIndex",
    },
    "layout": {
        "alignment", "marginL", "marginR", "marginV", "positionX", "positionY",
    },
    # For native we only allow solid color here. Gradient objects force advanced.
    "colors": {"fill", "outline", "background"},
    "outline": {"color", "width", "alignment", "layers", "shadow"},
    "background": {"enabled", "color"},
    "motion": {
        "mode", "origin", "graph",
        "preset", "entry", "exit", "entrance", "hold", "duration", "outDuration", "delay",
        "easing", "curve", "accel", "strength", "scale", "offsetX",
        "offsetY", "blur", "overshoot",
    },
    "wordHighlight": {"mode", "terms", "color", "granularity", "scale", "duration"},
    # Glow is a known capability. Its enabled state, rather than the mere
    # presence of a persisted disabled object, decides whether Native can own.
    "effects": {"blur", "shadow", "glow"},
}

MOTION_MODE_NONE = "none"
MOTION_MODE_EXPLICIT = "explicit"
MOTION_SOURCE_NONE = "none"
MOTION_SOURCE_PRESET = "preset"
MOTION_SOURCE_VISUAL_GRAPH = "visual_graph"
FORBIDDEN_CODE_KEYS = {
    "code", "source", "component", "raw", "raw_ass", "rawAss", "react",
    "javascript", "typescript", "script",
}
SAFE_ASS_TAGS = frozenset({
    "bord", "shad", "blur", "c", "3c", "4c", "fscx", "fscy", "frz",
    "move", "pos", "fad", "fade", "t", "clip", "k", "kf", "ko",
})


class StyleRecipeValidationError(ValueError):
    pass


class NativeRecipeUnsupportedError(StyleRecipeValidationError):
    pass


class StrokeAlignment(str, Enum):
    OUTSIDE = "OUTSIDE"
    CENTER = "CENTER"
    INSIDE = "INSIDE"


def normalize_stroke_alignment(value: Any = None) -> str:
    alignment = str(value or StrokeAlignment.OUTSIDE.value).strip().upper()
    if alignment != StrokeAlignment.OUTSIDE.value:
        raise StyleRecipeValidationError(
            f"stroke alignment {alignment} is not supported by the production renderers"
        )
    return alignment


@dataclass(frozen=True)
class FillSpec:
    """One validated fill contract shared by Studio, recipes and renderers."""

    kind: str
    color: str = "#FFFFFFFF"
    stops: tuple[dict[str, Any], ...] = ()
    angle: float = 0.0

    @classmethod
    def solid(cls, color: str) -> "FillSpec":
        return cls("solid", color=str(color or "#FFFFFFFF")).validate()

    @classmethod
    def linear(cls, stops, *, angle: float = 0.0) -> "FillSpec":
        return cls("linear-gradient", stops=tuple(copy.deepcopy(list(stops))), angle=float(angle)).validate()

    @classmethod
    def radial(cls, stops) -> "FillSpec":
        return cls("radial-gradient", stops=tuple(copy.deepcopy(list(stops)))).validate()

    @classmethod
    def from_value(cls, value: Any) -> "FillSpec":
        if isinstance(value, FillSpec):
            return value.validate()
        if not isinstance(value, Mapping):
            return cls.solid(str(value or "#FFFFFFFF"))
        # VisualCueSnapshot is allowed to retain the dataclass-shaped `kind`
        # field while persisted recipes and renderer graphs use `type`.
        kind = str(value.get("type") or value.get("kind") or "solid").strip().lower()
        if kind == "solid":
            return cls.solid(str(value.get("color") or "#FFFFFFFF"))
        normalized = "radial-gradient" if "radial" in kind else "linear-gradient"
        return cls(
            normalized,
            stops=tuple(copy.deepcopy(list(value.get("stops") or ()))),
            angle=float(value.get("angle", 0) or 0),
        ).validate()

    def validate(self) -> "FillSpec":
        kind = str(self.kind or "solid").lower()
        if kind not in {"solid", "linear-gradient", "radial-gradient"}:
            raise StyleRecipeValidationError("fill type must be solid, linear-gradient or radial-gradient")
        if kind == "solid":
            if not _valid_color(self.color):
                raise StyleRecipeValidationError("solid fill color invalid")
            return self
        _validate_gradient(self.to_dict())
        return self

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "solid":
            return {"type": "solid", "color": str(self.color)}
        return {
            "type": self.kind,
            "stops": [
                {
                    "color": str(stop.get("color") or "#FFFFFFFF"),
                    "position": float(stop.get("position", stop.get("pos", 0)) or 0),
                }
                for stop in self.stops
            ],
            "angle": float(self.angle),
        }

    def to_recipe_value(self) -> str | dict[str, Any]:
        return str(self.color) if self.kind == "solid" else self.to_dict()


def _valid_color(value: Any) -> bool:
    text = str(value or "")
    return text.startswith("#") and len(text) in {7, 9} and all(
        character in "0123456789abcdefABCDEF" for character in text[1:]
    )


def _section(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise StyleRecipeValidationError(f"{name} must be an object")
    return copy.deepcopy(dict(value))


def _motion_graph_tracks(value: Mapping[str, Any] | None) -> list[Any]:
    motion = value if isinstance(value, Mapping) else {}
    graph = motion.get("graph") if isinstance(motion.get("graph"), Mapping) else {}
    tracks = graph.get("tracks") if isinstance(graph, Mapping) else ()
    return list(tracks) if isinstance(tracks, (list, tuple)) else []


def motion_mode(value: Mapping[str, Any] | None) -> str:
    """Resolve legacy motion dictionaries to one explicit temporal state."""

    motion = value if isinstance(value, Mapping) else {}
    if _motion_graph_tracks(motion):
        return MOTION_MODE_EXPLICIT
    declared = str(motion.get("mode") or "").strip().lower()
    if declared in {MOTION_MODE_NONE, MOTION_MODE_EXPLICIT}:
        if declared == MOTION_MODE_NONE and _motion_graph_tracks(motion):
            return MOTION_MODE_EXPLICIT
        return declared
    preset = str(motion.get("preset") or "none").strip().lower()
    if preset not in {"", "none"}:
        return MOTION_MODE_EXPLICIT
    for key in ("entrance", "entry", "hold", "exit"):
        part = motion.get(key)
        if isinstance(part, Mapping):
            kind = str(part.get("type") or "none").strip().lower()
            if kind not in {"", "none"} or bool(part.get("keyframes")):
                return MOTION_MODE_EXPLICIT
        elif key in {"entry", "exit"} and str(part or "none").strip().lower() not in {"", "none"}:
            return MOTION_MODE_EXPLICIT
    return MOTION_MODE_NONE


def motion_source(value: Mapping[str, Any] | None, *, visual_graph: Mapping[str, Any] | None = None) -> str:
    """Classify choreography without pretending Graph Motion is a preset."""

    motion = value if isinstance(value, Mapping) else {}
    declared = str(motion.get("origin") or motion.get("source") or "").strip().lower()
    graph = visual_graph if isinstance(visual_graph, Mapping) else {}
    graph_motion = graph.get("motionGraph") if isinstance(graph.get("motionGraph"), Mapping) else {}
    graph_tracks = graph_motion.get("tracks") if isinstance(graph_motion, Mapping) else ()
    if _motion_graph_tracks(motion) or (isinstance(graph_tracks, (list, tuple)) and graph_tracks):
        return MOTION_SOURCE_VISUAL_GRAPH
    if declared in {MOTION_SOURCE_PRESET, MOTION_SOURCE_VISUAL_GRAPH}:
        return declared
    if motion_mode(motion) == MOTION_MODE_EXPLICIT:
        return MOTION_SOURCE_PRESET
    return MOTION_SOURCE_NONE


def normalize_motion_contract(value: Mapping[str, Any] | None) -> dict[str, Any]:
    motion = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    mode = motion_mode(motion)
    source = motion_source(motion)
    if mode == MOTION_MODE_NONE and source == MOTION_SOURCE_NONE:
        return {"mode": MOTION_MODE_NONE, "origin": MOTION_SOURCE_NONE}
    motion["mode"] = MOTION_MODE_EXPLICIT
    motion["origin"] = source if source != MOTION_SOURCE_NONE else MOTION_SOURCE_PRESET
    motion.pop("source", None)
    return motion


def normalize_shadow_contract(value: Any) -> dict[str, Any]:
    """Canonical glyph-shadow semantics shared by UI, snapshots and renderers."""

    if isinstance(value, Mapping):
        raw = copy.deepcopy(dict(value))
        strength = max(0.0, float(raw.get("strength", raw.get("distance", 0)) or 0))
        color = str(raw.get("color") or "#FF000000")
        if not _valid_color(color):
            raise StyleRecipeValidationError("outline.shadow.color invalid")
        color_alpha = int(color[1:3], 16) / 255.0 if len(color) == 9 else 1.0
        if len(color) == 9:
            color = "#FF" + color[3:]
        opacity = raw.get("opacity")
        if opacity is None:
            has_shape = any(
                float(raw.get(key, 0) or 0) != 0
                for key in (
                    "offset_x", "offsetX", "offset_y", "offsetY",
                    "blur_radius", "blur", "spread",
                )
            )
            opacity = min(0.78, strength * 0.24) if strength > 0 else (
                color_alpha if has_shape else 0.0
            )
        else:
            opacity = float(opacity or 0)
            if opacity > 1.0:
                opacity /= 100.0
            opacity *= color_alpha
        offset_x = float(raw.get("offset_x", raw.get("offsetX", strength)) or 0)
        offset_y = float(raw.get("offset_y", raw.get("offsetY", strength)) or 0)
        blur = max(
            0.0,
            min(
                40.0,
                float(raw.get("blur_radius", raw.get("blur", strength * 1.5)) or 0),
            ),
        )
        spread = max(0.0, min(20.0, float(raw.get("spread", 0) or 0)))
        enabled = bool(raw.get("enabled", True)) and opacity > 0 and (
            offset_x != 0 or offset_y != 0 or blur > 0 or spread > 0
        )
    else:
        strength = max(0.0, float(value or 0))
        opacity = min(0.78, strength * 0.24)
        offset_x = offset_y = strength
        blur = min(40.0, strength * 1.5)
        spread = 0.0
        enabled = strength > 0
        color = "#FF000000"
    return {
        "enabled": enabled,
        "color": color,
        "opacity": max(0.0, min(1.0, opacity)),
        "offset_x": offset_x,
        "offset_y": offset_y,
        "blur_radius": blur,
        "blur": blur,
        "spread": spread,
        "strength": strength,
    }


def normalize_glow_contract(value: Any) -> dict[str, Any]:
    """Canonical glow semantics shared by UI, LIVE, Fidelity and Export."""

    raw = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    if not raw and value not in (None, False, 0, 0.0, ""):
        raw = {"strength": value}
    strength = max(
        0.0,
        min(
            40.0,
            float(raw.get("strength", raw.get("radius", raw.get("blur", 0))) or 0),
        ),
    )
    radius = max(
        0.0,
        min(40.0, float(raw.get("radius", raw.get("blur", strength)) or 0)),
    )
    spread = max(0.0, min(20.0, float(raw.get("spread", 0) or 0)))
    intensity = max(0.0, min(4.0, float(raw.get("intensity", 1.0) or 0)))
    color = str(raw.get("color") or "#FFFFFFFF")
    if not _valid_color(color):
        raise StyleRecipeValidationError("effects.glow.color invalid")
    opacity_value = raw.get("opacity")
    if opacity_value is None:
        opacity = min(0.9, 0.24 + radius * 0.045) if radius > 0 else 0.0
    else:
        opacity = float(opacity_value or 0)
        if opacity > 1.0:
            opacity /= 100.0
    enabled = bool(raw.get("enabled", radius > 0)) and radius > 0 and opacity > 0 and intensity > 0
    return {
        "enabled": enabled,
        "color": color,
        "opacity": max(0.0, min(1.0, opacity)),
        "radius": radius,
        # Keep the compatibility name consumed by the Remotion schema.
        "blur": radius,
        "intensity": intensity,
        "spread": spread,
        "strength": strength if strength > 0 else radius,
    }


def _safe_json(value: Any, path: str = "recipe", depth: int = 0) -> None:
    if depth > 8:
        raise StyleRecipeValidationError(f"{path} is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            text = str(key)
            if text in FORBIDDEN_CODE_KEYS:
                raise StyleRecipeValidationError(f"{path}.{text} cannot contain renderer code")
            _safe_json(item, f"{path}.{text}", depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise StyleRecipeValidationError(f"{path} contains too many items")
        for index, item in enumerate(value):
            _safe_json(item, f"{path}[{index}]", depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise StyleRecipeValidationError(f"{path} contains a non-JSON value")


def _finite_number(value: Any, path: str, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StyleRecipeValidationError(f"{path} must be a number") from exc
    if not lo <= number <= hi:
        raise StyleRecipeValidationError(f"{path} out of range")
    return number


def _ass_color_value(value: Any, path: str) -> str:
    text = str(value or "")
    if not _valid_color(text):
        raise StyleRecipeValidationError(f"{path} must be #RRGGBB or #AARRGGBB")
    digits = text[1:]
    if len(digits) == 6:
        alpha, red, green, blue = "00", digits[0:2], digits[2:4], digits[4:6]
    else:
        qt_alpha = int(digits[0:2], 16)
        alpha, red, green, blue = f"{255 - qt_alpha:02X}", digits[2:4], digits[4:6], digits[6:8]
    return f"&H{alpha}{blue}{green}{red}&"


@dataclass
class ASSRecipe:
    """Validated libass override tags. Raw ASS strings are never accepted."""

    enabled: bool = False
    tags: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: Any) -> "ASSRecipe":
        if isinstance(value, ASSRecipe):
            return copy.deepcopy(value).validate()
        if value in (None, {}):
            return cls()
        if not isinstance(value, Mapping):
            raise StyleRecipeValidationError("ass must be an object")
        return cls(bool(value.get("enabled", False)), copy.deepcopy(list(value.get("tags") or []))).validate()

    def validate(self) -> "ASSRecipe":
        self.enabled = bool(self.enabled)
        if not isinstance(self.tags, list) or len(self.tags) > 32:
            raise StyleRecipeValidationError("ass.tags must be a list with at most 32 entries")
        for index, tag in enumerate(self.tags):
            self._validate_tag(tag, f"ass.tags[{index}]")
        return self

    @classmethod
    def _validate_tag(cls, tag: Any, path: str, *, nested: bool = False) -> None:
        if not isinstance(tag, Mapping):
            raise StyleRecipeValidationError(f"{path} must be an object")
        unknown = set(tag) - {"name", "value", "values", "start_ms", "end_ms", "accel", "tags"}
        if unknown:
            raise StyleRecipeValidationError(f"{path} has unknown fields: {sorted(unknown)}")
        name = str(tag.get("name") or "").lstrip("\\").lower()
        if name not in SAFE_ASS_TAGS or (nested and name == "t"):
            raise StyleRecipeValidationError(f"{path}.name is not an allowed ASS tag")
        if name in {"c", "3c", "4c"}:
            _ass_color_value(tag.get("value"), f"{path}.value")
            return
        if name in {"bord", "shad", "blur"}:
            _finite_number(tag.get("value"), f"{path}.value", 0, 100)
            return
        if name in {"fscx", "fscy"}:
            _finite_number(tag.get("value"), f"{path}.value", 1, 1000)
            return
        if name == "frz":
            _finite_number(tag.get("value"), f"{path}.value", -3600, 3600)
            return
        if name in {"k", "kf", "ko"}:
            _finite_number(tag.get("value"), f"{path}.value", 0, 100000)
            return
        if name in {"pos", "move", "fad", "fade", "clip"}:
            expected = {"pos": {2}, "move": {4, 6}, "fad": {2}, "fade": {7}, "clip": {4}}[name]
            values = tag.get("values")
            if not isinstance(values, list) or len(values) not in expected:
                raise StyleRecipeValidationError(f"{path}.values has an invalid length")
            bounds = (-100000, 100000) if name in {"pos", "move", "clip"} else (0, 3_600_000)
            for value_index, value in enumerate(values):
                _finite_number(value, f"{path}.values[{value_index}]", *bounds)
            return
        nested_tags = tag.get("tags")
        if not isinstance(nested_tags, list) or not nested_tags or len(nested_tags) > 12:
            raise StyleRecipeValidationError(f"{path}.tags must contain 1-12 safe tags")
        for child_index, child in enumerate(nested_tags):
            cls._validate_tag(child, f"{path}.tags[{child_index}]", nested=True)
        _finite_number(tag.get("start_ms", 0), f"{path}.start_ms", 0, 3_600_000)
        _finite_number(tag.get("end_ms", 0), f"{path}.end_ms", 0, 3_600_000)
        _finite_number(tag.get("accel", 1), f"{path}.accel", 0.01, 100)

    @classmethod
    def _compile_tag(cls, tag: Mapping[str, Any]) -> str:
        name = str(tag.get("name") or "").lstrip("\\").lower()
        if name in {"c", "3c", "4c"}:
            return f"\\{name}{_ass_color_value(tag.get('value'), f'ass.{name}')}"
        if name in {"pos", "move", "fad", "fade", "clip"}:
            values = ",".join(f"{float(value):g}" for value in tag.get("values", []))
            return f"\\{name}({values})"
        if name == "t":
            nested = "".join(cls._compile_tag(child) for child in tag.get("tags", []))
            return f"\\t({float(tag.get('start_ms', 0)):g},{float(tag.get('end_ms', 0)):g},{float(tag.get('accel', 1)):g},{nested})"
        return f"\\{name}{float(tag.get('value', 0)):g}"

    def to_override(self) -> str:
        self.validate()
        return "" if not self.enabled else "".join(self._compile_tag(tag) for tag in self.tags)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"enabled": self.enabled, "tags": copy.deepcopy(self.tags)}


@dataclass
class StyleRecipe:
    name: str
    engine: str = "native"
    typography: dict[str, Any] = field(default_factory=dict)
    layout: dict[str, Any] = field(default_factory=dict)
    colors: dict[str, Any] = field(default_factory=dict)
    outline: dict[str, Any] = field(default_factory=dict)
    background: dict[str, Any] = field(default_factory=dict)
    motion: dict[str, Any] = field(default_factory=dict)
    word_highlight: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)
    ass: ASSRecipe = field(default_factory=ASSRecipe)
    visual_graph: dict[str, Any] = field(default_factory=dict)
    web_theme: dict[str, Any] = field(default_factory=dict)

    def fill_spec(self) -> FillSpec:
        return FillSpec.from_value(self.colors.get("fill", "#FFFFFFFF"))

    def set_fill(self, fill: FillSpec | Mapping[str, Any] | str) -> None:
        spec = FillSpec.from_value(fill)
        self.colors["fill"] = spec.to_recipe_value()
        if spec.kind != "solid":
            self.engine = "remotion"

    def validate(self) -> None:
        self.name = str(self.name or "").strip()
        if not self.name:
            raise StyleRecipeValidationError("name must not be empty")
        if len(self.name) > 120:
            raise StyleRecipeValidationError("name must be at most 120 characters")
        self.engine = str(self.engine or "native").strip().lower()
        if self.engine not in {"native", "remotion"}:
            raise StyleRecipeValidationError("engine must be native or remotion")
        for name in (
            "typography", "layout", "colors", "outline", "background",
            "motion", "word_highlight", "effects",
        ):
            setattr(self, name, _section(getattr(self, name), name))
        self.motion = normalize_motion_contract(self.motion)
        if "shadow" in self.outline:
            self.outline["shadow"] = normalize_shadow_contract(self.outline["shadow"])
        if "glow" in self.effects:
            self.effects["glow"] = normalize_glow_contract(self.effects["glow"])
        self.ass = ASSRecipe.from_value(self.ass)
        self.visual_graph = _section(self.visual_graph, "visualGraph")
        if self.visual_graph:
            from .visual_design_graph import (
                VisualDesignGraph,
                VisualDesignGraphValidationError,
            )

            try:
                self.visual_graph = VisualDesignGraph.from_dict(self.visual_graph).to_dict()
            except VisualDesignGraphValidationError as exc:
                raise StyleRecipeValidationError(f"visualGraph invalid: {exc}") from exc
        self.web_theme = _section(self.web_theme, "webTheme")
        if self.web_theme:
            from .web_theme import WebThemeDocument, WebThemeValidationError

            try:
                self.web_theme = WebThemeDocument.from_dict(self.web_theme).to_dict()
            except WebThemeValidationError as exc:
                raise StyleRecipeValidationError(f"webTheme invalid: {exc}") from exc
            # Web themes render through the Remotion/Chromium pipeline only.
            self.engine = "remotion"
        if "fill" in self.colors:
            FillSpec.from_value(self.colors.get("fill"))
        _safe_json(self.to_dict(validate=False))

    def to_dict(self, *, validate: bool = True) -> dict[str, Any]:
        if validate:
            self.validate()
        payload = {
            "name": self.name,
            "engine": self.engine,
            "typography": copy.deepcopy(self.typography),
            "layout": copy.deepcopy(self.layout),
            "colors": copy.deepcopy(self.colors),
            "outline": copy.deepcopy(self.outline),
            "background": copy.deepcopy(self.background),
            "motion": copy.deepcopy(self.motion),
            "wordHighlight": copy.deepcopy(self.word_highlight),
            "effects": copy.deepcopy(self.effects),
            "ass": self.ass.to_dict(),
        }
        if self.visual_graph:
            payload["visualGraph"] = copy.deepcopy(self.visual_graph)
        if self.web_theme:
            payload["webTheme"] = copy.deepcopy(self.web_theme)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StyleRecipe":
        if not isinstance(payload, Mapping):
            raise StyleRecipeValidationError("recipe root must be an object")
        unknown = set(payload) - set(RECIPE_FIELDS)
        if unknown:
            raise StyleRecipeValidationError(f"unknown recipe fields: {sorted(unknown)}")
        recipe = cls(
            name=str(payload.get("name") or ""),
            engine=str(payload.get("engine") or "native"),
            typography=_section(payload.get("typography"), "typography"),
            layout=_section(payload.get("layout"), "layout"),
            colors=_section(payload.get("colors"), "colors"),
            outline=_section(payload.get("outline"), "outline"),
            background=_section(payload.get("background"), "background"),
            motion=_section(payload.get("motion"), "motion"),
            word_highlight=_section(payload.get("wordHighlight"), "wordHighlight"),
            effects=_section(payload.get("effects"), "effects"),
            ass=ASSRecipe.from_value(payload.get("ass")),
            visual_graph=_section(payload.get("visualGraph"), "visualGraph"),
            web_theme=_section(payload.get("webTheme"), "webTheme"),
        )
        recipe.validate()
        return recipe


@dataclass(frozen=True)
class RecipeRoute:
    engine: str
    reasons: tuple[str, ...] = ()


@dataclass
class NativeStylePlan:
    style: SubtitleStyle
    effect: dict[str, Any]


@dataclass
class MotionRecipe:
    """Renderer-neutral choreography; keyframes never contain executable code."""

    entrance: dict[str, Any] = field(default_factory=dict)
    hold: dict[str, Any] = field(default_factory=dict)
    exit: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "MotionRecipe":
        for name in ("entrance", "hold", "exit"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise StyleRecipeValidationError(f"motion.{name} must be an object")
            _safe_json(value, f"motion.{name}")
            keyframes = value.get("keyframes", [])
            if keyframes is not None and not isinstance(keyframes, list):
                raise StyleRecipeValidationError(f"motion.{name}.keyframes must be a list")
            for index, frame in enumerate(keyframes or []):
                if not isinstance(frame, Mapping):
                    raise StyleRecipeValidationError(f"motion.{name}.keyframes[{index}] must be an object")
                try:
                    time_ms = float(frame.get("t", 0))
                except (TypeError, ValueError):
                    raise StyleRecipeValidationError(f"motion.{name}.keyframes[{index}].t invalid")
                if not 0 <= time_ms <= 30_000:
                    raise StyleRecipeValidationError(f"motion.{name}.keyframes[{index}].t out of range")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"entrance": copy.deepcopy(self.entrance), "hold": copy.deepcopy(self.hold), "exit": copy.deepcopy(self.exit)}


@dataclass
class VisualStyleRecipe:
    """AI-facing visual design contract, separate from subtitle text/QC."""

    name: str
    engine_requirement: str = "native"
    typography: dict[str, Any] = field(default_factory=dict)
    fill: dict[str, Any] | str = field(default_factory=lambda: {"type": "solid", "color": "#FFFFFFFF"})
    strokes: list[dict[str, Any]] = field(default_factory=list)
    glow: dict[str, Any] = field(default_factory=dict)
    shadow: dict[str, Any] = field(default_factory=dict)
    background: dict[str, Any] = field(default_factory=dict)
    texture: dict[str, Any] = field(default_factory=dict)
    mask: dict[str, Any] = field(default_factory=dict)
    decorations: list[dict[str, Any]] = field(default_factory=list)
    layout: dict[str, Any] = field(default_factory=dict)
    emphasis_strategy: dict[str, Any] = field(default_factory=dict)
    motion: MotionRecipe = field(default_factory=MotionRecipe)
    ass: ASSRecipe = field(default_factory=ASSRecipe)
    visual_graph: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "VisualStyleRecipe":
        self.name = str(self.name or "").strip()
        if not self.name or len(self.name) > 120:
            raise StyleRecipeValidationError("visual recipe name invalid")
        self.engine_requirement = str(self.engine_requirement or "native").lower()
        if self.engine_requirement not in {"native", "advanced"}:
            raise StyleRecipeValidationError("engine_requirement must be native or advanced")
        for section_name, value in (
            ("typography", self.typography), ("glow", self.glow),
            ("shadow", self.shadow), ("background", self.background),
            ("texture", self.texture), ("mask", self.mask),
            ("layout", self.layout), ("emphasis_strategy", self.emphasis_strategy),
        ):
            if not isinstance(value, Mapping):
                raise StyleRecipeValidationError(f"{section_name} must be an object")
            _safe_json(value, section_name)
        self.fill = FillSpec.from_value(self.fill).to_dict()
        self.shadow = normalize_shadow_contract(self.shadow)
        self.glow = normalize_glow_contract(self.glow)
        if not isinstance(self.strokes, list) or len(self.strokes) > 4:
            raise StyleRecipeValidationError("strokes must contain at most 4 layers")
        for stroke in self.strokes:
            if not isinstance(stroke, Mapping):
                raise StyleRecipeValidationError("stroke must be an object")
            _safe_json(stroke, "strokes")
            try:
                if not 0 <= float(stroke.get("width", 0)) <= 30:
                    raise ValueError
            except (TypeError, ValueError):
                raise StyleRecipeValidationError("stroke.width out of range")
        if not isinstance(self.decorations, list) or len(self.decorations) > 16:
            raise StyleRecipeValidationError("decorations must be a short list")
        for decoration in self.decorations:
            if not isinstance(decoration, Mapping) or not str(decoration.get("type", "")):
                raise StyleRecipeValidationError("decoration type required")
            _safe_json(decoration, "decorations")
        if not isinstance(self.motion, MotionRecipe):
            self.motion = MotionRecipe(**dict(self.motion)) if isinstance(self.motion, Mapping) else MotionRecipe()
        self.motion.validate()
        self.ass = ASSRecipe.from_value(self.ass)
        if self.visual_graph:
            from .visual_design_graph import VisualDesignGraph

            self.visual_graph = VisualDesignGraph.from_dict(
                self.visual_graph
            ).to_dict()
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "engine_requirement": self.engine_requirement,
            "typography": copy.deepcopy(self.typography),
            "fill": copy.deepcopy(self.fill),
            "strokes": copy.deepcopy(self.strokes),
            "glow": copy.deepcopy(self.glow),
            "shadow": copy.deepcopy(self.shadow),
            "background": copy.deepcopy(self.background),
            "texture": copy.deepcopy(self.texture),
            "mask": copy.deepcopy(self.mask),
            "decorations": copy.deepcopy(self.decorations),
            "layout": copy.deepcopy(self.layout),
            "emphasis_strategy": copy.deepcopy(self.emphasis_strategy),
            "motion": self.motion.to_dict(),
            "ass": self.ass.to_dict(),
            "visual_graph": copy.deepcopy(self.visual_graph),
        }

    def to_style_recipe(self) -> StyleRecipe:
        self.validate()
        fill = FillSpec.from_value(self.fill).to_recipe_value()
        strokes = self.strokes or [{"color": "#FF000000", "width": 3}]
        first = strokes[0]
        # Keep the renderer-neutral three-phase timeline intact.  Reducing it
        # to a preset name made replay/export diverge from the design shown in
        # Studio and discarded hold/exit choreography.
        motion = self.motion.to_dict()
        background = copy.deepcopy(self.background)
        background.setdefault("enabled", False)
        background.setdefault("color", background.get("fill", "#00000000"))
        recipe = StyleRecipe(
            name=self.name,
            engine="native",
            typography={
                "fontFamily": self.typography.get("font_family", self.typography.get("fontFamily", "Microsoft YaHei UI")),
                "fontSize": self.typography.get("font_size", self.typography.get("fontSize", 52)),
                "bold": bool(self.typography.get("weight", 400) >= 700 or self.typography.get("bold", False)),
                "spacing": self.typography.get("letter_spacing", self.typography.get("spacing", 0)),
            },
            layout={"alignment": 2, "marginV": 64, **copy.deepcopy(self.layout)},
            colors={"fill": fill, "outline": first.get("color", "#FF000000"), "background": background.get("color", "#00000000")},
            outline={"layers": copy.deepcopy(strokes), "color": first.get("color", "#FF000000"), "width": first.get("width", 3), "shadow": copy.deepcopy(self.shadow)},
            background=background,
            motion=motion,
            word_highlight=copy.deepcopy(self.emphasis_strategy),
            effects={
                "glow": copy.deepcopy(self.glow),
                "texture": copy.deepcopy(self.texture),
                "mask": copy.deepcopy(self.mask),
                "decorations": copy.deepcopy(self.decorations),
            },
            ass=copy.deepcopy(self.ass),
            visual_graph=copy.deepcopy(self.visual_graph),
        )
        if route_recipe(recipe).engine == "remotion" or self.engine_requirement == "advanced":
            recipe.engine = "remotion"
        recipe.validate()
        return recipe

    @classmethod
    def from_style_recipe(cls, recipe: StyleRecipe) -> "VisualStyleRecipe":
        recipe.validate()
        fill = recipe.fill_spec().to_dict()
        outline = recipe.outline or {"color": recipe.colors.get("outline", "#FF000000"), "width": 3}
        visual = cls(
            name=recipe.name,
            engine_requirement="advanced" if route_recipe(recipe).engine == "remotion" else "native",
            typography=copy.deepcopy(recipe.typography),
            fill=fill,
            strokes=[{"color": outline.get("color", "#FF000000"), "width": outline.get("width", 3)}],
            glow=copy.deepcopy(recipe.effects.get("glow", {})) if isinstance(recipe.effects, Mapping) else {},
            shadow=normalize_shadow_contract(outline.get("shadow", 0)),
            background=copy.deepcopy(recipe.background),
            texture=copy.deepcopy(recipe.effects.get("texture", {})) if isinstance(recipe.effects, Mapping) else {},
            mask=copy.deepcopy(recipe.effects.get("mask", {})) if isinstance(recipe.effects, Mapping) else {},
            decorations=copy.deepcopy(recipe.effects.get("decorations", [])) if isinstance(recipe.effects, Mapping) else [],
            layout=copy.deepcopy(recipe.layout),
            emphasis_strategy=copy.deepcopy(recipe.word_highlight),
            motion=MotionRecipe(
                entrance=copy.deepcopy(recipe.motion.get("entrance", recipe.motion.get("entry", {}))),
                hold=copy.deepcopy(recipe.motion.get("hold", {})),
                exit=copy.deepcopy(recipe.motion.get("exit", {})),
            ),
            ass=copy.deepcopy(recipe.ass),
            visual_graph=copy.deepcopy(recipe.visual_graph),
        )
        visual.validate()
        return visual


def recipe_payload_for_style(recipes: Mapping[str, Any] | None, style_id: str) -> Mapping[str, Any] | None:
    """Find the recipe for a cue style id, including fill/scope/cue derived copies."""
    mapping = recipes or {}
    payload = mapping.get(style_id)
    if payload:
        return payload
    text = str(style_id or "")
    for token in ("-fill-", "-scope-", "-cue-", "-canvas-"):
        if token in text:
            payload = mapping.get(text.split(token, 1)[0])
            if payload:
                return payload
    return None


@lru_cache(maxsize=128)
def _route_serialized_recipe(payload: str) -> RecipeRoute:
    return _route_recipe_uncached(json.loads(payload))


def route_recipe(recipe: StyleRecipe | VisualStyleRecipe | Mapping[str, Any]) -> RecipeRoute:
    # Cache by content, never dict identity: nested in-place edits still
    # invalidate routing. Validation runs once per distinct saved payload.
    if isinstance(recipe, Mapping):
        try:
            payload = json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        except (TypeError, ValueError):
            return _route_recipe_uncached(recipe)
        return _route_serialized_recipe(payload)
    return _route_recipe_uncached(recipe)


def _route_recipe_uncached(recipe: StyleRecipe | VisualStyleRecipe | Mapping[str, Any]) -> RecipeRoute:
    if isinstance(recipe, VisualStyleRecipe):
        recipe.validate()
        reasons = []
        if recipe.engine_requirement == "advanced":
            reasons.append("visual recipe requires advanced renderer")
        if FillSpec.from_value(recipe.fill).kind != "solid":
            reasons.append("gradient fill requires advanced renderer")
        if recipe.background.get("enabled") and set(recipe.background) - {"enabled", "color"}:
            reasons.append("composited background card requires advanced renderer")
        if recipe.texture or recipe.mask or recipe.decorations:
            reasons.append("texture, mask or decorations require advanced renderer")
        for part in (recipe.motion.entrance, recipe.motion.hold, recipe.motion.exit):
            if isinstance(part, Mapping) and str(part.get("type") or "none") not in {"none", "fade", "slide", "scale"}:
                reasons.append("complex kinetic motion requires advanced renderer")
                break
        for gap in renderer_capability_gaps(VisualRenderer.NATIVE, recipe):
            reason = (
                f"capability {gap.capability.value} requires "
                f"{gap.minimum.name.lower()}: {gap.reason}"
            )
            if reason not in reasons:
                reasons.append(reason)
        return RecipeRoute("remotion" if reasons else "native", tuple(reasons))
    value = recipe if isinstance(recipe, StyleRecipe) else StyleRecipe.from_dict(recipe)
    value.validate()
    if value.engine == "remotion":
        return RecipeRoute("remotion", ("recipe explicitly requests the advanced renderer",))
    # Gradient fill or advanced visual features force the advanced renderer.
    fill = value.colors.get("fill") if isinstance(value.colors, Mapping) else None
    if _is_gradient(fill):
        return RecipeRoute("remotion", ("gradient fill requires advanced renderer",))
    reasons: list[str] = []
    for gap in renderer_capability_gaps(VisualRenderer.NATIVE, value.to_dict()):
        reasons.append(
            f"capability {gap.capability.value} requires {gap.minimum.name.lower()}: {gap.reason}"
        )
    sections = value.to_dict()
    for section_name, allowed in NATIVE_SECTION_KEYS.items():
        # Optional advanced fields are emitted by the graph serializer even
        # when they are empty.  Empty decorations/visualEffects and the
        # default line spacing do not change pixels and must not reroute an
        # otherwise native solid recipe to Remotion.
        unknown = {
            key for key in set(sections[section_name]) - allowed
            if sections[section_name].get(key) not in (None, "", False, 0, 0.0, [], {}, ())
            and not (
                section_name == "typography"
                and key == "lineSpacing"
                and abs(float(sections[section_name].get(key, 1.0)) - 1.0) < 1e-9
            )
        }
        if unknown:
            reasons.append(f"{section_name}: unsupported {', '.join(sorted(unknown))}")
    motion = value.motion
    preset = str(motion.get("preset") or "none")
    if preset not in builtin_effects():
        reasons.append(f"motion: unsupported preset {preset}")
    for part_name in ("entry", "exit"):
        part = motion.get(part_name)
        if isinstance(part, Mapping):
            effect_type = str(part.get("type") or "none")
            if effect_type not in EFFECT_TYPES:
                reasons.append(f"motion.{part_name}: unsupported type {effect_type}")
    highlight_mode = str(value.word_highlight.get("mode") or "none")
    if highlight_mode not in TEXT_EFFECT_TYPES | {"none"}:
        reasons.append(f"wordHighlight: unsupported mode {highlight_mode}")
    blur = value.effects.get("blur")
    entry = motion.get("entry") if isinstance(motion.get("entry"), Mapping) else {}
    if blur not in (None, 0, 0.0, False) and preset != "blur_reveal" and entry.get("type") != "blur_reveal":
        reasons.append("effects: blur requires the Native blur_reveal motion")
    if not reasons:
        try:
            candidate = _apply_motion_controls(builtin_effects()[preset], motion)
            if highlight_mode != "none":
                highlight_part: dict[str, Any] = {"type": highlight_mode}
                for source, target in (
                    ("terms", "terms"), ("color", "color"),
                    ("granularity", "granularity"), ("duration", "duration"),
                    ("scale", "overshoot"),
                ):
                    if source in value.word_highlight:
                        highlight_part[target] = value.word_highlight[source]
                candidate["word_highlight"] = highlight_part
            validate_effect(candidate)
        except (KeyError, TypeError, ValueError) as exc:
            reasons.append(f"motion: {exc}")
    return RecipeRoute("remotion" if reasons else "native", tuple(reasons))



def _is_gradient(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    t = str(value.get("type", "")).lower()
    return t in {"linear", "linear-gradient", "radial", "radial-gradient"} and bool(value.get("stops"))

def _validate_gradient(g: Mapping[str, Any]) -> None:
    t = str(g.get("type", "")).lower()
    if t not in {"linear", "linear-gradient", "radial", "radial-gradient"}:
        raise StyleRecipeValidationError("gradient type must be linear or radial")
    stops = g.get("stops")
    if not isinstance(stops, (list, tuple)) or len(stops) < 2:
        raise StyleRecipeValidationError("gradient requires at least 2 stops")
    seen = set()
    for i, s in enumerate(stops):
        if not isinstance(s, Mapping):
            raise StyleRecipeValidationError(f"gradient.stop[{i}] must be object")
        col = str(s.get("color", ""))
        if not (col.startswith("#") and len(col) in (7, 9)):
            raise StyleRecipeValidationError(f"gradient.stop[{i}].color invalid")
        pos = s.get("pos", s.get("position", None))
        try:
            pos = float(pos) if pos is not None else (i / (len(stops)-1))
        except Exception:
            pos = i / (len(stops)-1)
        if not (0.0 <= pos <= 1.0):
            raise StyleRecipeValidationError(f"gradient.stop[{i}].pos out of [0,1]")
        if pos in seen:
            # allow but warn in future; for now just accept
            pass
        seen.add(pos)
    ang = g.get("angle", 0)
    try:
        float(ang)
    except Exception:
        raise StyleRecipeValidationError("gradient.angle must be number")

def _value(mapping: Mapping[str, Any], key: str, default: Any) -> Any:
    return mapping[key] if key in mapping and mapping[key] is not None else default


def _apply_motion_controls(effect: dict[str, Any], motion: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(effect)
    entry = result.setdefault("entry", {"type": "none"})
    exit_part = result.setdefault("exit", {"type": "none"})
    if isinstance(motion.get("entry"), Mapping):
        entry = {**entry, **dict(motion["entry"])}
        result["entry"] = entry
    if isinstance(motion.get("exit"), Mapping):
        exit_part = {**exit_part, **dict(motion["exit"])}
        result["exit"] = exit_part
    aliases = {
        "duration": "duration", "delay": "delay", "easing": "easing",
        "curve": "easing", "accel": "accel", "strength": "strength",
        "scale": "scale_from", "offsetX": "offset_x", "offsetY": "offset_y",
        "blur": "blur", "overshoot": "overshoot",
    }
    for source, target in aliases.items():
        if source in motion and entry.get("type") != "none":
            entry[target] = motion[source]
    if "outDuration" in motion and exit_part.get("type") != "none":
        exit_part["duration"] = motion["outDuration"]
    return result


def compile_native_recipe(
    recipe: StyleRecipe | VisualStyleRecipe | Mapping[str, Any],
    *,
    style_id: str = "recipe",
) -> NativeStylePlan:
    value = recipe.to_style_recipe() if isinstance(recipe, VisualStyleRecipe) else (recipe if isinstance(recipe, StyleRecipe) else StyleRecipe.from_dict(recipe))
    route = route_recipe(value)
    if route.engine != "native":
        raise NativeRecipeUnsupportedError("; ".join(route.reasons))

    typography, layout, colors = value.typography, value.layout, value.colors
    outline, background = value.outline, value.background
    shadow_state = normalize_shadow_contract(
        _value(outline, "shadow", _value(value.effects, "shadow", 1))
    )
    native_shadow = float(shadow_state["strength"])
    if bool(shadow_state["enabled"]) and native_shadow <= 0:
        native_shadow = max(
            abs(float(shadow_state["offset_x"])),
            abs(float(shadow_state["offset_y"])),
        )
    fill_spec = FillSpec.from_value(_value(colors, "fill", "#FFFFFF"))
    style = SubtitleStyle(
        id=str(style_id or "recipe"),
        name=value.name,
        font_family=str(_value(typography, "fontFamily", "Microsoft YaHei UI")),
        font_size=float(_value(typography, "fontSize", 52)),
        font_weight=int(_value(typography, "fontWeight", 0)),
        font_style_name=str(_value(typography, "fontStyleName", "")),
        font_file=str(_value(typography, "fontFile", "")),
        font_face_index=int(_value(typography, "fontFaceIndex", 0)),
        primary_color=str(fill_spec.color),
        outline_color=str(_value(outline, "color", _value(colors, "outline", "#000000"))),
        outline_width=float(_value(outline, "width", 3)),
        shadow=native_shadow,
        bold=bool(_value(typography, "bold", False)),
        italic=bool(_value(typography, "italic", False)),
        underline=bool(_value(typography, "underline", False)),
        spacing=float(_value(typography, "spacing", 0)),
        alignment=int(_value(layout, "alignment", 2)),
        margin_l=int(_value(layout, "marginL", 40)),
        margin_r=int(_value(layout, "marginR", 40)),
        margin_v=int(_value(layout, "marginV", 42)),
        position_x=None if layout.get("positionX") is None else int(layout["positionX"]),
        position_y=None if layout.get("positionY") is None else int(layout["positionY"]),
        scale_x=float(_value(typography, "scaleX", 100)),
        scale_y=float(_value(typography, "scaleY", 100)),
        border_style=3 if bool(_value(background, "enabled", False)) else 1,
        back_color=str(_value(background, "color", _value(colors, "background", "#000000"))),
    )
    style.validate()

    preset = str(value.motion.get("preset") or "none")
    effect = _apply_motion_controls(builtin_effects()[preset], value.motion)
    if preset == "blur_reveal" and value.effects.get("blur") is not None:
        effect["entry"]["blur"] = value.effects["blur"]
    highlight = value.word_highlight
    mode = str(highlight.get("mode") or "none")
    if mode != "none":
        part: dict[str, Any] = {"type": mode}
        for source, target in (
            ("terms", "terms"), ("color", "color"),
            ("granularity", "granularity"), ("duration", "duration"),
            ("scale", "overshoot"),
        ):
            if source in highlight:
                part[target] = highlight[source]
        effect["word_highlight"] = part
    return NativeStylePlan(style=style, effect=validate_effect(effect))


def save_recipe(recipe: StyleRecipe, path: str | os.PathLike[str]) -> Path:
    recipe.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".recipe.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(recipe.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    return target



def compile_gradient(recipe: StyleRecipe) -> dict[str, Any] | None:
    """Return a normalized gradient description if present, else None.
    This is consumed by advanced renderers (Remotion etc.). Native ASS cannot do true gradient text reliably.
    """
    if not isinstance(recipe.colors, Mapping):
        return None
    fill = recipe.colors.get("fill")
    if not _is_gradient(fill):
        return None
    g = dict(fill)
    # Normalize stops to list of {color, pos, opacity}
    stops = []
    for s in g.get("stops", []):
        pos = s.get("pos", s.get("position", 0))
        try:
            pos = float(pos)
        except Exception:
            pos = 0.0
        stops.append({
            "color": str(s.get("color", "#FFFFFF")),
            "pos": max(0.0, min(1.0, pos)),
            "opacity": float(s.get("opacity", 1.0)) if s.get("opacity") is not None else 1.0,
        })
    g["stops"] = stops
    g["angle"] = float(g.get("angle", 0))
    g["type"] = str(g.get("type", "linear")).lower()
    return g

def load_recipe(path: str | os.PathLike[str]) -> StyleRecipe:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return StyleRecipe.from_dict(payload)
