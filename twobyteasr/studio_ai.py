"""Preview-only AI suggestions for Subtitle Studio cues and Effect DSL."""

from __future__ import annotations

import difflib
import hashlib
import base64
import json
import copy
import mimetypes
import re
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .studio_project import SubtitleStyle
from .ai_providers import AIProviderError
from .provider_registry import (
    GLOBAL_PROVIDER_REGISTRY,
    ProviderRequestState,
    ProviderStateMachine,
)


def provider_for_stage(settings, stage):
    """Compatibility seam for tests and integrations; no independent runtime."""
    return GLOBAL_PROVIDER_REGISTRY.client(stage=stage, settings=settings)
from .llm_adapter import get_last_llm_response_diagnostics
from .studio_commands import cue_by_id
from .studio_project import SubtitleProject
from .style_recipe import ASSRecipe, MotionRecipe, StyleRecipe, VisualStyleRecipe, route_recipe
from .font_system import system_font_inventory
from .studio_text_tools import parse_cleanup_payload, request_text_cleanup
from .visual_design_graph import (
    CompiledLiveScene,
    VisualDesignGraph,
    VisualDesignGraphValidationError,
    clean_subtitle_graph,
    comic_burst_graph,
    glitch_graph,
    graph_from_style_recipe,
    industrial_brass_hud_graph,
    manga_impact_graph,
    achievement_pop_graph,
    steam_gauge_graph,
    streamer_gaming_graph,
    structural_signature,
    style_recipe_from_graph,
    validate_structural_variants,
    victorian_mechanical_graph,
)
from .visual_runtime import VISUAL_CAPABILITY_MATRIX, VisualRenderer
from .art_direction import (
    ART_DIRECTION_SCHEMA,
    ART_DIRECTION_TEMPLATES,
    ART_DIRECTION_VERSION,
    ArtDirectionSpec,
    VisualQualityScore,
    art_direction_manifest,
    fallback_art_directions,
    validate_and_repair_graph,
    validate_graph_matches_instruction,
    validate_graph_for_direction,
    validate_variants_match_instruction,
)
from .ai_design_adapter import ProviderOutputAdapter
from .studio_project import studio_data_root


@dataclass(frozen=True)
class StudioSuggestion:
    cue_id: str
    before_text: str
    after_text: str
    effect: dict | None
    rationale: str

    def diff(self) -> str:
        return "\n".join(
            difflib.ndiff([self.before_text], [self.after_text])
        )


@dataclass(frozen=True)
class AIDesignSuggestion:
    """A renderer-neutral visual design proposal; it never rewrites speech."""

    cue_id: str
    recipe: StyleRecipe
    rationale: str = ""
    variants: tuple[VisualStyleRecipe, ...] = ()
    design_intent: str = ""
    visual_changes: tuple[str, ...] = ()
    motion_reason: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    provider_succeeded: bool = True
    provider_error_category: str = ""
    stage_timings_ms: Mapping[str, float] = field(default_factory=dict)
    art_directions: tuple[ArtDirectionSpec, ...] = ()
    quality_scores: tuple[VisualQualityScore, ...] = ()
    failure_stage: str = ""
    pipeline_status: Mapping[str, str] = field(default_factory=dict)
    repair_attempted: bool = False


class AIDesignStage(str, Enum):
    PREPARING_CONTEXT = "PREPARING_CONTEXT"
    CONNECTING_PROVIDER = "CONNECTING_PROVIDER"
    GENERATING = "GENERATING"
    PARSING = "PARSING"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    BUILDING_LIVE = "BUILDING_LIVE"
    RENDERING_FIDELITY = "RENDERING_FIDELITY"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AIDesignFailureStage(str, Enum):
    AUTH = "AUTH"
    HTTP = "HTTP"
    MODEL = "MODEL"
    PARSE = "PARSE"
    SCHEMA = "SCHEMA"
    QUALITY_VALIDATOR = "QUALITY_VALIDATOR"
    REPAIR = "REPAIR"
    FINAL = "FINAL"


def style_recipe_for_prompt(prompt: str) -> StyleRecipe:
    """Create a conservative, deterministic visual recipe for instant preview.

    The provider-backed design path may replace this draft later. Keeping this
    first result local makes the UI useful offline and guarantees that Apply
    always receives validated StyleRecipe rather than arbitrary code.
    """
    source = str(prompt or "").strip()
    text = source.casefold()
    requires_advanced = any(token in text for token in (
        "rgb channel", "channel separation", "通道分离", "动态遮罩",
        "dynamic mask", "复杂 glitch", "复杂故障", "多层动态",
    ))
    if any(token in text for token in (
        "1930s", "橡皮管", "胶片", "黑白复古", "复古动画",
        "rubber hose", "old cinema", "老电影",
    )):
        recipe = StyleRecipe(
            name="1930s Rubber Hose",
            engine="remotion",
            typography={"fontFamily": "KaiTi", "fontSize": 62, "bold": True, "spacing": 0.8},
            layout={"alignment": 2, "marginV": 64, "rotation": -0.8},
            colors={"fill": "#FFFFF1D4", "outline": "#FF151413", "background": "#00000000"},
            outline={"layers": [
                {"color": "#FF151413", "width": 7.0},
                {"color": "#FFF6E6C7", "width": 1.5},
            ], "color": "#FF151413", "width": 7.0, "shadow": 3.0},
            background={
                "enabled": True, "type": "film_card", "fill": "#E822201B",
                "color": "#E822201B", "gradient": {"colors": ["#F02A2721", "#E8161512"], "angle": 90},
                "opacity": 0.94, "padding_x": 34, "padding_y": 18, "radius": 4,
                "border": {"color": "#FFE9D3A8", "width": 2},
                "shadow": {"color": "#99000000", "offset_x": 4, "offset_y": 7, "blur": 12},
                "texture": {"type": "film_grain", "opacity": 0.24, "scale": 1.1, "seed": 1930},
                "transform": {"rotation": -0.7, "scale": 100, "offset_x": 0, "offset_y": 0},
                "marks": ["film_perforation", "vignette"],
            },
            effects={"glow": {"enabled": False}, "texture": {"type": "film_grain", "opacity": 0.24, "scale": 1.1, "seed": 1930}, "decorations": [{"type": "film_perforation"}, {"type": "vignette"}]},
            motion={
                "entrance": {"type": "squash_stretch", "duration_ms": 300, "overshoot": 1.15, "amplitude": 18, "seed": 1930},
                "hold": {"type": "film_gate", "amplitude": 1.8, "frequency": 9.5, "seed": 1930},
                "exit": {"type": "fade", "duration_ms": 170},
            },
            ass=ASSRecipe(True, [
                {"name": "fscx", "value": 92},
                {"name": "fscy", "value": 92},
                {"name": "t", "start_ms": 0, "end_ms": 240, "accel": 1.2, "tags": [
                    {"name": "fscx", "value": 100},
                    {"name": "fscy", "value": 100},
                    {"name": "frz", "value": 0.8},
                ]},
            ]),
        )
    elif any(token in text for token in ("手写", "纸片", "便签", "撕纸", "paper", "handwritten")):
        recipe = StyleRecipe(
            name="手写纸片",
            engine="remotion",
            typography={"fontFamily": "KaiTi", "fontSize": 60, "bold": True, "spacing": 1.2},
            layout={"alignment": 2, "marginV": 68, "rotation": -1.5},
            colors={"fill": {"type": "linear-gradient", "angle": 12, "stops": [
                {"color": "#FFFFF6E8", "position": 0.0},
                {"color": "#FFFF8D76", "position": 1.0},
            ]}, "outline": "#FF4A2D28", "background": "#E8FFF8E8"},
            outline={"layers": [
                {"color": "#FF4A2D28", "width": 4.0},
                {"color": "#FFFFD3B8", "width": 1.4},
            ], "shadow": 2.0},
            background={"enabled": True, "color": "#E8FFF8E8", "marks": ["torn_paper"]},
            effects={"glow": {"enabled": True, "color": "#FFFF8D76", "blur": 4, "opacity": 0.28}},
            motion={
                "entrance": {"type": "bounce_lite", "duration_ms": 260, "overshoot": 108},
                "hold": {"type": "paper_hold"},
                "exit": {"type": "soft_fade", "duration_ms": 160},
            },
            ass=ASSRecipe(True, [
                {"name": "fad", "values": [120, 120]},
                {"name": "frz", "value": -1.5},
            ]),
        )
    elif any(token in text for token in ("赛博", "cyberpunk", "2077", "hud", "故障")):
        # Real visual design, not a preset swap.
        # Typography + gradient + multi-layer stroke/glow + HUD + parameterized motion timeline.
        recipe = StyleRecipe(
            name="Cyberpunk HUD",
            engine="remotion",
            typography={
                "fontFamily": "Noto Sans SC",
                "fontSize": 58,
                "bold": True,
                "spacing": 1.5,
                "weight": 700,
            },
            layout={"alignment": 2, "marginV": 64},
            colors={
                # Yellow -> Cyan linear gradient (斜向)
                "fill": {
                    "type": "linear",
                    "stops": [
                        {"color": "#F9D84A", "pos": 0.0, "opacity": 1.0},
                        {"color": "#20D6E8", "pos": 1.0, "opacity": 1.0},
                    ],
                    "angle": 18,
                },
                "outline": "#0A0F12",
                "background": "#00000000",
            },
            outline={
                # Multi-layer stroke
                "layers": [
                    {"color": "#0A0F12", "width": 3.5, "opacity": 1.0},   # deep black
                    {"color": "#20D6E8", "width": 1.2, "opacity": 0.55}, # cyan low-alpha
                ],
                "shadow": 0.0,
            },
            background={
                "enabled": True,
                "type": "tech_frame",
                "color": "#00000000",
                "padding": [6, 10, 6, 10],
                "corner": "cut",
                "marks": ["left_bracket", "right_bracket", "scanline"],
            },
            effects={
                "glow": {"color": "#20D6E8", "blur": 6, "opacity": 0.35},
            },
            motion={
                "entrance": {
                    "type": "glitch_reveal", "duration_ms": 240,
                    "glitch_intensity": 0.9, "slice_count": 5,
                    "chromatic_offset": 6,
                },
                "hold": {
                    "scanline": True, "scan_speed": 1.7,
                    "micro_glitch_interval_ms": 1800,
                },
                "exit": {"type": "data_break", "duration_ms": 160},
            },
            word_highlight={"mode": "none"},
        )
    elif any(token in text for token in ("gaming impact", "游戏冲击", "重击", "punch")):
        recipe = StyleRecipe(
            name="Gaming Impact",
            engine="remotion",
            typography={"fontFamily": "Source Han Sans CN", "fontSize": 64, "bold": True, "spacing": 0.5},
            layout={"alignment": 2, "marginV": 70},
            colors={
                "fill": {"type": "linear", "angle": 90, "stops": [
                    {"color": "#FFFFFF", "pos": 0.0}, {"color": "#FFD84A", "pos": 1.0},
                ]},
                "outline": "#090A0C", "background": "#00000000",
            },
            outline={"layers": [
                {"color": "#090A0C", "width": 6.0},
                {"color": "#F05A28", "width": 2.0},
            ]},
            background={"enabled": True, "color": "#00000000", "marks": ["accent_line"]},
            effects={"glow": {"color": "#F05A28", "blur": 4, "opacity": 0.28}},
            motion={
                "entrance": {
                    "type": "gaming_impact", "duration_ms": 300,
                    "scale_keyframes": [0.70, 1.18, 0.96, 1.0],
                    "stroke_punch": 1.35, "vertical_squash": 0.92,
                    "shake_px": 3,
                },
                "hold": {"emphasis_pulse": 1.03, "pulse_once": True},
                "exit": {"type": "scale_fade", "duration_ms": 130},
            },
        )
    elif any(token in text for token in ("soft neon", "柔光霓虹", "柔和霓虹", "霓虹")):
        recipe = StyleRecipe(
            name="Soft Neon",
            engine="remotion",
            typography={"fontFamily": "Noto Sans SC", "fontSize": 56, "bold": True, "spacing": 2.0},
            layout={"alignment": 2, "marginV": 68},
            colors={
                "fill": {"type": "linear", "angle": 12, "stops": [
                    {"color": "#B7F5FF", "pos": 0.0}, {"color": "#F4B8FF", "pos": 1.0},
                ]},
                "outline": "#172133", "background": "#00000000",
            },
            outline={"layers": [{"color": "#172133", "width": 2.5}]},
            background={"enabled": False, "color": "#00000000", "marks": ["underline"]},
            effects={"glow": {"color": "#8CEBFF", "blur": 15, "opacity": 0.48}},
            motion={
                "entrance": {
                    "type": "soft_neon_reveal", "duration_ms": 420,
                    "offset_y": 14, "glow_overshoot": 1.25,
                },
                "hold": {"glow_breathing": True, "period_ms": 2400, "amplitude": 0.06},
                "exit": {"type": "fade_float_up", "duration_ms": 220, "offset_y": -8},
            },
        )
    elif any(token in text for token in ("可爱", "粉色", "少女", "二次元")):
        recipe = StyleRecipe(
            name="Anime Soft Pop",
            typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 54, "bold": True},
            colors={"fill": "#FFFFF7FB", "outline": "#FFB878C7"},
            outline={"color": "#FFB878C7", "width": 3.0, "shadow": 1.0},
            motion={"preset": "soft_pop", "duration": 180, "strength": "medium", "curve": "soft"},
        )
    else:
        recipe = StyleRecipe(
            name="AI 柔和对白",
            typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 52, "bold": True},
            colors={"fill": "#FFFFFFFF", "outline": "#FF26282B"},
            outline={"color": "#FF26282B", "width": 3.0, "shadow": 1.0},
            motion={
                "preset": "soft_fade", "exit": {"type": "soft_fade", "duration": 140},
                "duration": 180, "strength": "low", "curve": "soft",
            },
        )
    recipe.validate()
    # Unsupported Native fields are never silently discarded.
    route = route_recipe(recipe)
    if route.engine == "remotion" and recipe.engine == "native":
        recipe.engine = "remotion"
    return recipe


_STYLE_DESIGN_SYSTEM = """
You are a professional kinetic-subtitle designer. Return ONLY one compact JSON object; no markdown, prose, subtitle rewrite, code, raw ASS, renderer source, JavaScript, React, QML, or executable expressions.

First act as an art director and create exactly 3 materially different ArtDirectionSpec objects. Then act as a visual planner and compile each direction into its corresponding complete VisualDesignGraph V1. Do not skip directly from the prompt to renderer primitives. Differences limited to font or colors are invalid.

Root keys: design_intent (string), visual_changes (array of 3-12 strings), motion_reason (string), art_directions (array of exactly 3 ArtDirectionSpec objects), variants (array of exactly 3 corresponding VisualDesignGraph objects).
Each ArtDirectionSpec is semantic design intent, never renderer parameters. It must declare one dominant curated primary_family, optional secondary_family, family_mix with primary >= 60, hierarchy, composition, color/contrast strategy, temporal motion concept, decoration/effect strategy, density, readability, and explicit avoid rules. A/B/C primary directions must differ.
Every graph has: schema, version, name, seed, textLayer, panelLayer, decorationLayers, effectLayers, motionGraph.
Trusted panel primitives: NONE, ROUNDED_PANEL, RECTANGLE, COMIC_BURST, BADGE, RIBBON, CUT_CORNER, ANGLED_PLATE, BRACKET_FRAME, TECH_FRAME, COMIC_BUBBLE, UNDERLINE_SLAB, MARKER, TAPE, PIXEL_FRAME, PILL, TORN_PAPER, GLASS_PANEL, MECHANICAL_PLATE, STICKER, LOWER_THIRD.
Trusted decoration primitives: IMPACT_RAYS, SPEED_LINES, HALFTONE, SHARDS, ACCENT_BARS, SCANLINES, PIXEL_TILES, CROSSHAIR, INK_SPLAT, FLOAT_GLYPHS, SCAN_SWEEP, PARTICLES, ARROWS, DATA_BARS, GEARS, RIVETS, GAUGE, PIPES, STEAM.
Trusted effect primitives: GLITCH, IMPACT, RGB_SPLIT.
HARD FIDELITY CONTRACT — the user's Art Direction is a binding constraint, not a suggestion: when the instruction names a style family (e.g. 蒸汽朋克/steampunk, 赛博/cyber, 美漫/comic, 故障/glitch, 游戏/gaming), ALL THREE variants must belong to that direction as three materially different sub-styles (e.g. steampunk → Industrial Brass HUD / Victorian Mechanical Plate / Steam Gauge Typography). Jumping to an unrelated family (Clean Editorial, Manga, Cyber HUD for a steampunk request) is an automatic QUALITY FAIL. Descriptions must not fake design: every visual idea the direction prose declares must exist as a real graph primitive or typography feature — brass/copper/metallic means a multi-stop warm metallic gradient fill (never white solid text), gears means GEARS decoration, rivets means RIVETS, gauge/仪表 means GAUGE, pipes means PIPES, steam/烟雾 means STEAM, multilayer outline means >=2 strokes, glow means glow enabled, RGB split/色散 means an RGB_SPLIT effect layer.
Trusted motion properties: x,y,scale,scale_x,scale_y,rotation,opacity,rgb_offset,slice_offset,scanline_opacity,flicker,ray_scale,burst_scale,shake_x,shake_y,tracking,char_reveal,blur,mask_reveal.
Text-level visual motion: animate the glyphs themselves, not only boxes. `tracking` (target=text layer id) animates letter-spacing in px; `char_reveal` (target=text layer id) animates 0→1 per-character reveal for stagger entrances (combine with step keyframes and staggerMs for type-on rhythm); `blur` (px) animates focus — enter blurred and resolve sharp, or blur out on exit; `mask_reveal` (0→1) is a directional wipe on any layer, ideal for panel draw-on and text slice reconstruction.
Typography is mandatory design material, not a default. Each variant must treat the glyphs themselves: choose at least two of {gradient fill (linear stops), 2-3 stacked strokes of different width/color (e.g. thin outer + thick inner or double outline), deep offset shadow, glow, RGB split during entrance}. A plain solid fill with one thin stroke is invalid for variants A and C.
MotionGraph uses explicit target/property/keyframes with timeMs, numeric value, and easing. Targets must name group or an actual layer id. Use deterministic integer seeds. Keep a stable readable hold and a clean exit. Text, panel, and decorations must NOT move in lockstep — desynchronize them (text resolves first while the panel still draws on, or decorations lag with staggerMs).
Design principles: text is dominant; decoration supports semantic emphasis and participates in composition (aim speed lines/arrows toward the text, anchor data bars to the panel edge); dramatic motion has anticipation, impact, settle, a readable hold, and a clean exit. Use the curated fill_strategies and panel_vocabulary from the selected family. A controlled gradient is allowed where the family supports it, but Clean Editorial may remain solid.
Avoid plain rectangles behind text, linear scale 0-to-1 as the whole idea, default cyan/magenta on every design, random rays without hierarchy, and continuous shaking.
Do not default to simple linear scale/slide/fade. Use them only as components of a named effect family (IMPACT, COMIC_BURST, GLITCH_DIGITAL, STREAMER_POP, PUNCH, TYPE_STAGGER). Prefer temporal structure, staged decoration, controlled overshoot, effect-specific motion, and a readable hold. Glitch must recover; do not jitter the whole cue. Comic/gaming must animate panel or decorations, not only group scale. A/B/C motion signatures must differ. Easing should be ease-out, overshoot, spring, or step—not linear as the creative default. Entrance should stay within about 30% of the cue. The reading phase stays visually stable: hold motion is at most a very light secondary drift, never a loop of scale pulses.
Variant roles are mandatory and must read as three different designers worked on them: A is typography-led (weight/case/spacing/stroke contrast carries the design), B is shape/composition-led (panel geometry and decoration composition carry it), C is FX-led (text effects and motion texture carry it). No two variants may share the same panel primitive, the same decoration set, or the same motion-track structure. At least one variant must include a GLITCH or IMPACT effect layer wired to matching motion properties (rgb_offset, slice_offset, scanline_opacity, flicker, shake_x, shake_y). At least one variant must use panel primitive NONE or UNDERLINE_SLAB — a background box is never the default answer. Differences limited to color or font alone are invalid.

Curated visual directions (choose per variant when the user prompt fits; never mix all of them into one cue). Each entry lists structure / hierarchy / color strategy / typography strategy / motion strategy:
- Manga Impact: COMIC_BURST or ANGLED_PLATE + SPEED_LINES/ARROWS/INK_SPLAT behind ink text / text > burst > lines / grayscale ink + one red accent / heaviest weight, thick ink outline, optional TORN_PAPER panel / anticipation then impact overshoot.
- Cyber HUD: TECH_FRAME/BRACKET_FRAME or GLASS_PANEL + SCANLINES/SCAN_SWEEP/DATA_BARS/CROSSHAIR / text > frame > telemetry / derive accent from the video frame, never default cyan / medium weight + tracking settle entrance / line draw then lock.
- Retro CRT: panel NONE or RECTANGLE + SCANLINES + RGB_SPLIT + rolling slice_offset / text dominates a dark window / phosphor amber or green, not cyan / medium weight, slight letter spacing / signal break then stable lock.
- Pixel/Arcade: PIXEL_FRAME + PIXEL_TILES + step easing + char_reveal / text > frame > tiles / limited 4-color palette / blocky heavy font feel / pixel assemble, stepped hold.
- Streamer Gaming: BADGE/RIBBON or PILL + ACCENT_BARS/SPEED_LINES/PARTICLES / badge supports text / channel palette, warm accents / bold, one accent word / spring pop then calm.
- Clean Premium: panel NONE or GLASS_PANEL/MARKER/UNDERLINE_SLAB + gradient fill / text is the whole design / neutral pair + one reserved accent / light-to-mid weight, generous spacing, gradient fill or double stroke / mask_reveal draw-on, then stillness.
- Anime/Variety: COMIC_BUBBLE/MARKER or TAPE + FLOAT_GLYPHS + bouncy overshoot / playful offset composition / bright local colors / rounded feel, tilted axis / squash and settle.
- Kinetic Typography: panel NONE, the motion IS the design / staggered glyph rhythm / high contrast single hue / heavy + light weight mix / char_reveal + tracking choreography, per-word accents.
- Sports Broadcast: ANGLED_PLATE/CUT_CORNER or PILL + DATA_BARS/ACCENT_BARS, strong diagonal axis / score-team hierarchy / team color pair / condensed heavy caps / wipe entrance, tick hold.
- Comic Speech: COMIC_BUBBLE + ARROWS + HALFTONE accents / bubble carries the joke / paper white + ink / casual tilt / pop with tail wag.
- Sticker Pop: PILL or TORN_PAPER with thick white outer stroke on everything / sticker floats over video / saturated fill + white rim / bold rounded / drop with bounce and tiny idle float.
- Glass HUD: GLASS_PANEL + subtle PARTICLES/SCAN_SWEEP / translucent depth behind text / desaturated with one luminous accent / medium weight / soft blur reveal via blur 0→sharp.
- Manga Ink Splash: TORN_PAPER/ANGLED_PLATE + INK_SPLAT + SHARDS / ink mass frames text / pure black/white + one gray tone / brush-like heavy stroke feel / slash entrance then still.
- Broadcast Lower-Third: UNDERLINE_SLAB or RIBBON with restrained ACCENT_BARS / editorial hierarchy / muted complementary pair / light editorial type / mask_reveal wipe, professional stillness.
- Industrial Brass HUD (steampunk A): MECHANICAL_PLATE + RIVETS/GAUGE/PIPES / text > plate > instruments / brass-copper gradient on dark iron, warm metallic strokes, never neon / heavy weight, double stroke / plate draw-on, gauge needle damped-spring sweep, rivet pop, text mask_reveal.
- Victorian Mechanical Plate (steampunk B): MECHANICAL_PLATE ornate + GEARS both sides + STEAM drift / engraved plate carries serif-leaning text / aged copper + parchment + deep sepia outline / medium-heavy, generous spacing / plate settle, gears rotate continuously, steam drifts upward, char_reveal.
- Steam Gauge Typography (steampunk C): LOWER_THIRD slab + big GAUGE dial behind + RIVETS ring + STEAM / needle sweep is the entrance / aged gold dial markings, needle the only bright accent / radial aged-gold gradient fill / needle damped-spring sweep, then stable readable hold.

Exact key contract; do not add any other keys:
Graph = schema,version,name,seed,textLayer,panelLayer,decorationLayers,effectLayers,motionGraph.
textLayer = id,font,fill,strokes,shadow,glow,letterSpacing,lineSpacing,alignment,emphasis.
panelLayer = id,primitive,params. Each decoration/effect item = id,primitive,params,seed.
motionGraph = durationMs,staggerMs,tracks. Track = target,property,keyframes,postBehavior. postBehavior is HOLD by default and RESET only when explicitly intended. Keyframe = timeMs,value,easing.
font,fill,shadow,glow,emphasis,params must be JSON objects; strokes,decorationLayers,effectLayers,tracks,keyframes must be JSON arrays. font.weight is an integer from 100 to 1000, never a CSS word such as bold. Never use null: use {} or [] when empty.
Never put text, position, rotation, opacity, timing, or animation fields directly on textLayer.

font.family MUST be selected from available_fonts. Use the supplied visual_capability_manifest; do not claim or invent unsupported primitives. cue_text is context only and must not be rewritten. Explain the structural motion choice in motion_reason.
""".strip()

_STYLE_DESIGN_CLI_SYSTEM = """
Return ONLY compact JSON containing design_intent, visual_changes, motion_reason, exactly 3 semantic ArtDirectionSpec objects in art_directions, and exactly 3 corresponding complete VisualDesignGraph V1 objects in variants. Decide direction first, then plan the graph. No markdown, prose, subtitle rewrite, code, raw ASS, JavaScript, React, or renderer source.
FIDELITY CONTRACT: the user instruction is binding. When it names a style family (蒸汽朋克/steampunk, 赛博/cyber, 美漫/comic, 故障/glitch, 游戏/gaming, ...), all three variants must be materially different SUB-STYLES of that direction — never unrelated families. Prose must materialize: metallic/brass means multi-stop warm gradient fill, 齿轮→GEARS, 铆钉→RIVETS, 仪表→GAUGE, 管道→PIPES, 蒸汽/烟雾→STEAM, 多层描边→>=2 strokes, 辉光→glow, 色散→RGB_SPLIT. A graph that stays white-solid single-stroke under a rich description is rejected.
Each graph uses schema="2byte.visual-design-graph", version=1, name, deterministic seed, textLayer, panelLayer, decorationLayers, effectLayers, and motionGraph. Use only the trusted primitives and motion properties listed in the user context capability manifest. A/B/C must differ in panel/decorations/effects/MotionGraph structure AND in text treatment (fill kind, stroke stack, glow/shadow), not only font or color. font.family must come from available_fonts. Keep text readable during hold. Prefer text-level motion: tracking, char_reveal, blur (enter blurred then resolve sharp) and mask_reveal (directional wipe) on the text or panel layer.
Every variant must design the glyphs themselves: at least two of gradient fill, 2-3 stacked strokes, deep offset shadow, glow, entrance RGB split. A plain solid fill with one thin stroke is invalid for variants A and C.
Variant roles are mandatory: A typography-led, B shape/composition-led, C FX-led (text effects and motion texture carry the design). No two variants share the same panel primitive, decoration set, motion-track structure, or typography treatment. At least one variant uses a GLITCH or IMPACT effect layer with matching motion properties (rgb_offset/slice_offset/scanline_opacity/flicker/shake_x/shake_y); at least one variant uses panel primitive NONE or UNDERLINE_SLAB instead of a background box.
Exact keys only: Graph=schema,version,name,seed,textLayer,panelLayer,decorationLayers,effectLayers,motionGraph; textLayer=id,font,fill,strokes,shadow,glow,letterSpacing,lineSpacing,alignment,emphasis; panelLayer=id,primitive,params; decoration/effect item=id,primitive,params,seed; motionGraph=durationMs,staggerMs,tracks; track=target,property,keyframes,postBehavior; keyframe=timeMs,value,easing. postBehavior is HOLD unless an explicit RESET is wanted. font/fill/shadow/glow/emphasis/params are JSON objects; font.weight is integer 100-1000, never bold; strokes/decorationLayers/effectLayers/tracks/keyframes are arrays; never use null, use {} or []. Never put text, position, rotation, opacity, timing, or animation directly on textLayer.
""".strip()

_MOTION_ENTRANCE = [
    "none", "fade", "slide", "scale", "spring_pop", "overshoot", "slam",
    "wipe", "mask_reveal", "type_on", "letter_stagger", "flip", "rotate",
    "drop", "squash_stretch",
]
_MOTION_HOLD = [
    "none", "breath", "micro_jitter", "handheld", "wiggle", "float", "pulse",
    "flicker", "film_gate", "chromatic_split", "boil", "per_letter_bounce",
]
_MOTION_EXIT = [
    "none", "fade", "slide", "scale", "collapse", "scatter", "mask_close",
    "wipe", "drop", "blur_out",
]
_ASS_PRIMITIVES = [
    "fad", "fade", "t", "fscx", "fscy", "frz", "move", "pos", "blur",
    "bord", "shad", "c", "3c", "4c",
]

_VISUAL_GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "schema": {"type": "string", "enum": ["2byte.visual-design-graph"]},
        "version": {"type": "integer", "enum": [1]},
        "name": {"type": "string"},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "textLayer": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "font": {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string"},
                        "size": {"type": "number", "minimum": 8, "maximum": 500},
                        "weight": {"type": "integer", "minimum": 100, "maximum": 1000},
                        "italic": {"type": "boolean"},
                    },
                    "required": ["family", "size", "weight"],
                    "additionalProperties": False,
                },
                "fill": {"type": "object"},
                "strokes": {"type": "array", "items": {"type": "object"}, "maxItems": 4},
                "shadow": {"type": "object"},
                "glow": {"type": "object"},
                "letterSpacing": {"type": "number"},
                "lineSpacing": {"type": "number"},
                "alignment": {"type": "integer", "minimum": 1, "maximum": 9},
                "emphasis": {"type": "object"},
            },
            "required": [
                "id", "font", "fill", "strokes", "shadow", "glow",
                "letterSpacing", "lineSpacing", "alignment", "emphasis",
            ],
            "additionalProperties": False,
        },
        "panelLayer": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "primitive": {
                    "type": "string",
                    "enum": ["NONE", "ROUNDED_PANEL", "RECTANGLE", "COMIC_BURST", "BADGE", "RIBBON", "CUT_CORNER", "ANGLED_PLATE", "BRACKET_FRAME", "TECH_FRAME", "COMIC_BUBBLE", "UNDERLINE_SLAB", "MARKER", "TAPE", "PIXEL_FRAME", "PILL", "TORN_PAPER", "GLASS_PANEL"],
                },
                "params": {"type": "object"},
            },
            "required": ["id", "primitive", "params"],
            "additionalProperties": False,
        },
        "decorationLayers": {
            "type": "array",
            "maxItems": 24,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "primitive": {
                        "type": "string",
                        "enum": ["IMPACT_RAYS", "SPEED_LINES", "HALFTONE", "SHARDS", "ACCENT_BARS", "SCANLINES", "PIXEL_TILES", "CROSSHAIR", "INK_SPLAT", "FLOAT_GLYPHS", "SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS"],
                    },
                    "params": {"type": "object"},
                    "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                },
                "required": ["id", "primitive", "params", "seed"],
                "additionalProperties": False,
            },
        },
        "effectLayers": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                        "primitive": {"type": "string", "enum": ["GLITCH", "IMPACT", "RGB_SPLIT"]},
                    "params": {"type": "object"},
                    "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                },
                "required": ["id", "primitive", "params", "seed"],
                "additionalProperties": False,
            },
        },
        "motionGraph": {
            "type": "object",
            "properties": {
                "durationMs": {"type": "integer", "minimum": 1, "maximum": 30000},
                "staggerMs": {"type": "integer", "minimum": 0, "maximum": 5000},
                "tracks": {
                    "type": "array",
                    "maxItems": 96,
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "property": {
                                "type": "string",
                                "enum": [
                                    "x", "y", "scale", "scale_x", "scale_y", "rotation", "opacity",
                                    "rgb_offset", "slice_offset", "scanline_opacity", "flicker", "ray_scale",
                                    "burst_scale", "shake_x", "shake_y", "tracking", "char_reveal",
                                    "blur", "mask_reveal",
                                ],
                            },
                            "keyframes": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 64,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "timeMs": {"type": "integer", "minimum": 0, "maximum": 30000},
                                        "value": {"type": "number"},
                                        "easing": {
                                            "type": "string",
                                            "enum": [
                                                "linear", "ease-in", "ease-out", "ease-in-out",
                                                "overshoot", "step", "ease-out-expo",
                                                "ease-out-back", "spring", "damped-spring",
                                                "ease-in-out-cubic", "impact", "glitch",
                                            ],
                                        },
                                    },
                                    "required": ["timeMs", "value", "easing"],
                                    "additionalProperties": False,
                                },
                            },
                            "postBehavior": {"type": "string", "enum": ["HOLD", "RESET"]},
                        },
                        "required": ["target", "property", "keyframes", "postBehavior"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["durationMs", "staggerMs", "tracks"],
            "additionalProperties": False,
        },
    },
    "required": [
        "schema", "version", "name", "seed", "textLayer", "panelLayer",
        "decorationLayers", "effectLayers", "motionGraph",
    ],
    "additionalProperties": False,
}


_ART_DIRECTION_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "schema": {"type": "string", "enum": [ART_DIRECTION_SCHEMA]},
        "version": {"type": "integer", "enum": [ART_DIRECTION_VERSION]},
        "concept_name": {"type": "string"},
        "intent": {"type": "string"},
        "emotion": {"type": "string"},
        "visual_language": {"type": "string"},
        "reference_family": {"type": "string"},
        "hierarchy": {"type": "string"},
        "text_emphasis": {"type": "string"},
        "composition": {"type": "string"},
        "shape_language": {"type": "string"},
        "color_strategy": {"type": "string"},
        "contrast_strategy": {"type": "string"},
        "motion_concept": {"type": "string"},
        "entrance_feel": {"type": "string"},
        "hold_feel": {"type": "string"},
        "exit_feel": {"type": "string"},
        "decoration_strategy": {"type": "string"},
        "effect_strategy": {"type": "string"},
        "density": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "energy": {"type": "string"},
        "readability": {"type": "string"},
        "avoid": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 16},
        "primary_family": {"type": "string", "enum": list(ART_DIRECTION_TEMPLATES)},
        "secondary_family": {"type": "string"},
        "family_mix": {
            "type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
        },
        "regeneration_anchor": {"type": "string"},
    },
    "required": [
        "schema", "version", "concept_name", "intent", "emotion",
        "visual_language", "reference_family", "hierarchy", "text_emphasis",
        "composition", "shape_language", "color_strategy", "contrast_strategy",
        "motion_concept", "entrance_feel", "hold_feel", "exit_feel",
        "decoration_strategy", "effect_strategy", "density", "energy",
        "readability", "avoid", "primary_family", "secondary_family",
        "family_mix", "regeneration_anchor",
    ],
    "additionalProperties": False,
}


_VISUAL_GRAPH_DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "design_intent": {"type": "string"},
        "visual_changes": {
            "type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 12,
        },
        "motion_reason": {"type": "string"},
        "art_directions": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": _ART_DIRECTION_SPEC_SCHEMA,
        },
        "variants": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": _VISUAL_GRAPH_SCHEMA,
        },
    },
    "required": [
        "design_intent", "visual_changes", "motion_reason",
        "art_directions", "variants",
    ],
    "additionalProperties": False,
}


_CLI_DIRECTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "design_intent": {"type": "string"},
        "visual_changes": {
            "type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 12,
        },
        "motion_reason": {"type": "string"},
        "art_directions": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": _ART_DIRECTION_SPEC_SCHEMA,
        },
    },
    "required": ["design_intent", "visual_changes", "motion_reason", "art_directions"],
    "additionalProperties": False,
}

_CLI_VARIANT_SCHEMA = {
    "type": "object",
    "properties": {"variant": _VISUAL_GRAPH_SCHEMA},
    "required": ["variant"],
    "additionalProperties": False,
}


def _cli_two_phase_generate(
    provider: Any,
    system_prompt: str,
    request_context: Mapping[str, Any],
    *,
    frame_data_url: str,
    deadline_monotonic: float,
    cancel_check: Callable[[], bool] | None,
    trace: dict[str, Any],
    on_phase: Callable[[str], None],
) -> dict[str, Any]:
    """Generate designs for CLI agents in small phases.

    One request carrying three complete graphs is what pushes the CLI agent
    past its budget. Phase 1 plans the three art directions; phase 2 compiles
    each direction into one graph. Progress is reported between phases, and
    the assembled payload feeds the exact same parser/validators as the HTTP
    one-shot path.
    """

    def remaining() -> float:
        value = deadline_monotonic - time.monotonic()
        if value <= 0:
            raise AIProviderError("AI 视觉设计请求超时。", category="timeout")
        return value

    def phase_content(context: Mapping[str, Any]) -> object:
        text = json.dumps(context, ensure_ascii=False)
        if frame_data_url:
            return [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": frame_data_url}},
            ]
        return text

    def run_phase(label: str, request, schema, *, max_tokens: int, temperature: float):
        started_wall_ms = time.time() * 1000.0
        started_perf = time.perf_counter()
        timeout_seconds = remaining()
        entry = {
            "phase": str(label),
            "start_ms": round(started_wall_ms, 3),
            "timeout_seconds": round(timeout_seconds, 3),
        }
        phase_trace = trace.setdefault("provider", {}).setdefault("phase_trace", [])
        if isinstance(phase_trace, list):
            phase_trace.append(entry)
        try:
            result = provider.structured_complete(
                request,
                schema,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_seconds,
                cancel_check=cancel_check,
                stage="studio_visual_design",
            )
        except BaseException as exc:
            entry.update({
                "end_ms": round(time.time() * 1000.0, 3),
                "duration_ms": round((time.perf_counter() - started_perf) * 1000.0, 3),
                "error_category": str(getattr(exc, "category", type(exc).__name__)),
            })
            history = getattr(provider, "process_trace_history", None)
            if isinstance(history, list):
                trace.setdefault("provider", {})["processes"] = copy.deepcopy(history)
            raise
        entry.update({
            "end_ms": round(time.time() * 1000.0, 3),
            "duration_ms": round((time.perf_counter() - started_perf) * 1000.0, 3),
            "result_type": type(result).__name__,
        })
        history = getattr(provider, "process_trace_history", None)
        if isinstance(history, list):
            trace.setdefault("provider", {})["processes"] = copy.deepcopy(history)
        return result

    phase1_context = {
        key: value for key, value in request_context.items()
        if key != "visual_graph_schema"
    }
    phase1_context["need"] = (
        "Phase 1 of 2: output ONLY design_intent, visual_changes, motion_reason "
        "and exactly 3 structurally different semantic ArtDirectionSpec objects "
        "(art_directions: A typography-led, B shape/composition-led, C FX-led). "
        "Do not output variants or any VisualDesignGraph in this phase."
    )
    on_phase("directions")
    directions_payload = run_phase(
        "directions",
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": phase_content(phase1_context)},
        ],
        _CLI_DIRECTIONS_SCHEMA,
        max_tokens=3000,
        temperature=0.85,
    )
    if not isinstance(directions_payload, Mapping):
        raise AIProviderError(
            "AI 没有返回 JSON 对象。", category="structured_json_parse_error"
        )
    directions = directions_payload.get("art_directions")
    if (
        not isinstance(directions, list)
        or len(directions) != 3
        or not all(isinstance(item, Mapping) for item in directions)
    ):
        raise AIProviderError(
            "AI 方向规划必须返回三个 ArtDirectionSpec。", category="schema"
        )
    variants: list[Any] = []
    for index, direction in enumerate(directions):
        slot = chr(65 + index)
        phase2_context = {
            key: value for key, value in request_context.items()
            if key != "visual_graph_schema"
        }
        phase2_context["variant_slot"] = slot
        phase2_context["art_direction"] = dict(direction)
        phase2_context["need"] = (
            f"Phase 2 of 2: compile the provided art_direction (variant {slot}) "
            "into ONE complete VisualDesignGraph V1 object. Output only "
            '{"variant": <graph>}. Honor the direction; do not redesign it. '
            f"Variant {slot} must stay structurally different from other slots."
        )
        on_phase(f"compile_{slot}")
        variant_payload = run_phase(
            f"compile_{slot}",
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": phase_content(phase2_context)},
            ],
            _CLI_VARIANT_SCHEMA,
            max_tokens=3500,
            temperature=0.5,
        )
        graph = (
            variant_payload.get("variant")
            if isinstance(variant_payload, Mapping)
            else variant_payload
        )
        if not isinstance(graph, Mapping):
            raise AIProviderError(
                f"方案 {slot} 编译结果不是 JSON 对象。", category="schema"
            )
        variants.append(graph)
    trace.setdefault("provider", {})["cli_phases"] = [
        "directions", "compile_A", "compile_B", "compile_C",
    ]
    return {
        "design_intent": str(directions_payload.get("design_intent") or ""),
        "visual_changes": [
            str(item)
            for item in (directions_payload.get("visual_changes") or [])
            if isinstance(item, (str, int, float))
        ],
        "motion_reason": str(directions_payload.get("motion_reason") or ""),
        "art_directions": [dict(item) for item in directions],
        "variants": variants,
    }


def available_font_shortlist(limit: int = 30) -> dict[str, list[str]]:
    """Return only fonts Qt can render in this Windows session, grouped for AI."""
    try:
        families = [entry.family for entry in system_font_inventory()]
    except Exception:
        families = []
    categories: dict[str, list[str]] = {
        "chinese_display": [],
        "chinese_sans": [],
        "serif": [],
        "handwriting": [],
        "pixel_game": [],
        "cartoon": [],
    }
    rules = {
        "chinese_display": ("hei", "yahei", "source han", "noto sans", "deng", "黑体"),
        "chinese_sans": ("sans", "hei", "yahei", "等线", "黑体"),
        "serif": ("serif", "song", "simsun", "fangsong", "宋", "仿宋", "明朝"),
        "handwriting": ("kai", "kaiti", "hand", "xing", "楷", "行书", "手写"),
        "pixel_game": ("pixel", "fusion", "unifont", "terminal", "mono", "像素", "cubic", "俐方体", "zpix", "崩音"),
        "cartoon": ("comic", "round", "youyuan", "圆", "cartoon"),
    }
    for family in families:
        lowered = family.casefold()
        for category, needles in rules.items():
            if any(needle in lowered for needle in needles):
                categories[category].append(family)
    preferred = (
        "Noto Sans SC", "Source Han Sans CN", "Microsoft YaHei UI",
        "Microsoft YaHei", "SimHei", "KaiTi", "FangSong", "SimSun",
    )
    installed = {family.casefold(): family for family in families}
    fallback = [installed[item.casefold()] for item in preferred if item.casefold() in installed]
    if not fallback:
        fallback = families[:8]
    for category, values in categories.items():
        categories[category] = list(dict.fromkeys([*values, *fallback]))[: max(1, limit // 3)]
    return categories


_MOTION_TRIGGER_WORDS = (
    "动画", "活泼", "故障", "弹跳", "复古", "手写", "卡通", "震动",
    "冲击", "出现", "展开", "animation", "glitch", "bounce", "retro",
    "handwritten", "cartoon", "shake", "impact", "reveal", "unfold",
    "游戏", "直播", "爆裂", "爆炸", "动态", "美漫", "gaming",
    "streamer", "explosion", "dynamic", "comic", "hud",
)


def _motion_required(instruction: str) -> bool:
    text = str(instruction or "").casefold()
    return any(token in text for token in _MOTION_TRIGGER_WORDS)


def _comic_graph_required(instruction: str) -> bool:
    text = str(instruction or "").casefold()
    return any(
        token in text
        for token in ("美漫", "爆裂", "爆炸", "comic", "burst", "explosion")
    )


def _glitch_graph_required(instruction: str) -> bool:
    text = str(instruction or "").casefold()
    return any(token in text for token in ("故障", "glitch"))


def _visual_graph_semantic_requirements(instruction: str) -> list[str]:
    requirements = [
        "Each graph must implement its corresponding ArtDirectionSpec primary family, not all prompt keywords.",
        "Use only the allowed layers from that direction's primary/secondary curated family manifest.",
    ]
    if _motion_required(instruction):
        requirements.append("Every variant must have a non-empty meaningful MotionGraph.")
    return requirements


def _font_fallback(fonts: Mapping[str, list[str]], category: str = "chinese_sans") -> str:
    values = list(fonts.get(category) or [])
    if values:
        return values[0]
    for fallback in fonts.values():
        if fallback:
            return fallback[0]
    return "Microsoft YaHei UI"


def _normalize_recipe_font(recipe: StyleRecipe, fonts: Mapping[str, list[str]]) -> None:
    allowed = {
        family.casefold(): family
        for values in fonts.values()
        for family in values
        if str(family).strip()
    }
    family = str(recipe.typography.get("fontFamily") or "").strip()
    category = str(recipe.typography.get("fallbackCategory") or "chinese_sans")
    recipe.typography.pop("fallbackCategory", None)
    if allowed and family.casefold() not in allowed:
        recipe.typography["fontFamily"] = _font_fallback(fonts, category)
    elif family and family.casefold() in allowed:
        recipe.typography["fontFamily"] = allowed[family.casefold()]


def _normalize_graph_font(
    graph: VisualDesignGraph,
    fonts: Mapping[str, list[str]],
) -> None:
    allowed = {
        family.casefold(): family
        for values in fonts.values()
        for family in values
        if str(family).strip()
    }
    family = str(graph.text_layer.font.get("family") or "").strip()
    if allowed and family.casefold() not in allowed:
        graph.text_layer.font["family"] = _font_fallback(fonts)
    elif family and family.casefold() in allowed:
        graph.text_layer.font["family"] = allowed[family.casefold()]


def _compact_cli_family_vocabulary() -> list[dict[str, Any]]:
    """Family → trusted layer/panel/fill/easing/motion vocabulary only.

    The full curated manifest also carries prose constraints the compact CLI
    system contract already states; repeating them per request is what pushed
    the CLI generate prompt past its timeout.
    """
    return [
        {
            "family_id": item["family_id"],
            "allowed_layers": item["allowed_layers"],
            "panel_vocabulary": item["panel_vocabulary"],
            "fill_strategies": item["fill_strategies"],
            "easing": item["easing"],
            "motion_vocabulary": item["motion_vocabulary"],
        }
        for item in art_direction_manifest()
    ]


def visual_capability_manifest() -> dict[str, dict[str, str]]:
    return {
        renderer.value: {
            capability.value: support.name
            for capability, support in capabilities.items()
        }
        for renderer, capabilities in VISUAL_CAPABILITY_MATRIX.items()
    }


def _project_style_profile(project: SubtitleProject, cue_id: str) -> dict[str, Any]:
    cue = cue_by_id(project, cue_id)
    style = next((item for item in project.styles if item.id == cue.style_id), None)
    speaker = next((item for item in project.speakers if item.id == cue.speaker_id), None)
    width = int(project.media.width or project.render_settings.get("play_res_x", 1920) or 1920)
    height = int(project.media.height or project.render_settings.get("play_res_y", 1080) or 1080)
    safe_area = project.render_settings.get("safe_area")
    if not isinstance(safe_area, Mapping):
        safe_area = {
            "left": round(width * 0.05),
            "right": round(width * 0.05),
            "top": round(height * 0.05),
            "bottom": round(height * 0.10),
        }
    palette = list(dict.fromkeys(
        str(value)
        for item in project.styles
        for value in (item.primary_color, item.outline_color, item.outline2_color)
        if str(value).strip()
    ))[:12]
    return {
        "speaker": {
            "id": cue.speaker_id,
            "role": speaker.name if speaker is not None else cue.speaker_id,
            "color": speaker.color if speaker is not None else "",
        },
        "resolution": {"width": width, "height": height},
        "safe_area": dict(safe_area),
        "current_style": {
            "name": style.name if style is not None else "",
            "font_family": style.font_family if style is not None else "",
            "font_size": style.font_size if style is not None else 0,
            "fill": style.primary_color if style is not None else "",
            "outline": style.outline_color if style is not None else "",
        },
        "project_profile": {
            "cue_count": len(project.cues),
            "speaker_count": len(project.speakers),
            "style_count": len(project.styles),
            "palette": palette,
        },
    }


def _vision_data_url(path: str | Path | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        if not candidate.is_file() or candidate.stat().st_size > 5 * 1024 * 1024:
            return ""
        mime = mimetypes.guess_type(candidate.name)[0] or "image/jpeg"
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{mime};base64,{encoded}"


def _recipe_signature(recipe: StyleRecipe) -> tuple[str, str, str, str, str, str]:
    return (
        str(recipe.typography.get("fontFamily") or "").casefold(),
        json.dumps(recipe.colors.get("fill"), ensure_ascii=False, sort_keys=True),
        json.dumps(recipe.outline, ensure_ascii=False, sort_keys=True),
        json.dumps(recipe.background, ensure_ascii=False, sort_keys=True),
        json.dumps({"motion": recipe.motion, "ass": recipe.ass.to_dict()}, ensure_ascii=False, sort_keys=True),
        json.dumps(recipe.layout, ensure_ascii=False, sort_keys=True),
    )


def _semantic_richness(recipe: StyleRecipe, instruction: str) -> tuple[int, tuple[str, ...]]:
    """Score soft style cues; names alone never satisfy a visual direction."""
    text = str(instruction or "").casefold()
    payload = json.dumps(recipe.to_dict(), ensure_ascii=False, sort_keys=True).casefold()
    hits: list[str] = []
    if any(token in text for token in ("1930s", "rubber hose", "橡皮管", "old film", "old cinema", "胶片", "老电影")):
        fill = json.dumps(recipe.colors.get("fill"), ensure_ascii=False).casefold()
        if any(token in fill for token in ("fff1d4", "ffe8be", "f6e6c7", "sepia", "cream")):
            hits.append("cream-sepia palette")
        layers = recipe.outline.get("layers", []) if isinstance(recipe.outline, Mapping) else []
        if len(layers) >= 2 or float(recipe.outline.get("width", 0) or 0) >= 4:
            hits.append("bold irregular outline")
        background = recipe.background if isinstance(recipe.background, Mapping) else {}
        if background.get("enabled") and str(background.get("type") or background.get("style") or "none") != "none":
            hits.append("film card")
        if any(token in payload for token in ("film_grain", "flicker", "film_gate", "grain", "vignette")):
            hits.append("film texture")
        if any(token in payload for token in ("squash", "jitter", "boil", "wiggle", "spring_pop", "overshoot")):
            hits.append("rubber motion")
        font = str(recipe.typography.get("fontFamily") or "").casefold()
        if any(token in font for token in ("kai", "serif", "song", "hand", "comic")):
            hits.append("retro font")
    return len(hits), tuple(hits)


def _parse_design_payload(
    payload: Mapping[str, Any],
    instruction: str,
    fonts: Mapping[str, list[str]],
) -> tuple[
    list[StyleRecipe], str, tuple[str, ...], str,
    tuple[ArtDirectionSpec, ...], tuple[VisualQualityScore, ...],
]:
    # Providers may return semantic proposals rather than renderer DTOs.  The
    # adapter translates those fields before the strict graph validator runs.
    adapted = False
    variant_rows = payload.get("variants")
    if not isinstance(variant_rows, list):
        variant_rows = next(
            (payload.get(key) for key in ("proposals", "designs", "directions")
             if isinstance(payload.get(key), list)),
            None,
        )
    if isinstance(variant_rows, list) and any(
        isinstance(item, Mapping)
        and not (item.get("schema") == "2byte.visual-design-graph" or "textLayer" in item or "motionGraph" in item)
        for item in variant_rows
    ):
        payload = ProviderOutputAdapter().adapt_payload(payload, instruction=instruction)
        adapted = True
    variants_payload = payload.get("variants")
    if not isinstance(variants_payload, list) or len(variants_payload) != 3:
        raise RuntimeError("AI 必须返回三个 A/B/C 视觉方案。")
    graph_payload = all(
        isinstance(item, Mapping)
        and (
            item.get("schema") == "2byte.visual-design-graph"
            or "textLayer" in item
            or "motionGraph" in item
        )
        for item in variants_payload
    )
    if graph_payload:
        try:
            graphs = [VisualDesignGraph.from_dict(item) for item in variants_payload]
            directions_payload = payload.get("art_directions")
            directions_present = isinstance(directions_payload, list) and len(directions_payload) == 3
            directions = (
                tuple(ArtDirectionSpec.from_dict(item) for item in directions_payload)
                if directions_present else fallback_art_directions(instruction)
            )
            if directions_present and len({
                (item.primary_family, item.concept_name.casefold())
                for item in directions
            }) != 3:
                raise VisualDesignGraphValidationError(
                    "A/B/C ArtDirectionSpec objects must be materially different"
                )
            quality_scores: list[VisualQualityScore] = []
            for index, graph in enumerate(graphs):
                _normalize_graph_font(graph, fonts)
                graph.validate()
                if _motion_required(instruction) and not graph.motion_graph.tracks:
                    raise VisualDesignGraphValidationError(
                        "dynamic design requires a non-empty MotionGraph"
                    )
                # Pre-ArtDirection providers and existing integrations may
                # return complete graph variants without semantic direction
                # objects. Keep those payloads valid by applying structural
                # graph/quality validation without inventing a mismatched
                # direction contract. New payloads still receive the full
                # direction-aware gate above.
                direction = directions[index] if directions_present else None
                graph, quality = validate_and_repair_graph(
                    graph, direction, deadline_ms=40.0,
                )
                graphs[index] = graph
                if direction is not None:
                    validate_graph_for_direction(graph, direction)
                    # The user's Art Direction words are a hard constraint on
                    # each graph, not free prose: explicitly requested
                    # primitives/typography must materialize here.
                    validate_graph_matches_instruction(instruction, direction, graph)
                quality_scores.append(quality)
                if not quality.accepted:
                    raise VisualDesignGraphValidationError(
                        "VISUAL_QUALITY: " + "; ".join(quality.issues or ("score below threshold",))
                    )
                CompiledLiveScene.compile(graph)
            # Triple-level intent binding: 蒸汽朋克 stays steampunk across
            # A/B/C — unrelated families (Clean Editorial / Manga / Cyber)
            # under a named direction are an automatic quality failure.
            if directions_present:
                validate_variants_match_instruction(instruction, directions, graphs)
            if not adapted:
                # Native graph payloads must be structurally diverse; the
                # provider had full expressive power.
                validate_structural_variants(graphs)
            elif len({graph.stable_hash() for graph in graphs}) != 3:
                # Semantic payloads were flattened by the adapter; structural
                # distance is not expressible there. Exact duplicates still
                # fail; family/concept uniqueness is checked above.
                raise VisualDesignGraphValidationError(
                    "A/B/C variants must be materially different"
                )
        except (TypeError, ValueError, VisualDesignGraphValidationError) as exc:
            raise RuntimeError(f"AI 返回的 VisualDesignGraph 无法校验：{exc}") from exc
        recipes = [style_recipe_from_graph(graph) for graph in graphs]
        changes = payload.get("visual_changes")
        return (
            recipes,
            str(payload.get("design_intent") or "").strip(),
            tuple(str(item) for item in changes if str(item).strip())
            if isinstance(changes, list) else (),
            str(payload.get("motion_reason") or "").strip(),
            directions,
            tuple(quality_scores),
        )
    raise RuntimeError(
        "Provider must return three complete VisualDesignGraph V1 variants; legacy StyleRecipe is not accepted"
    )


def _design_failure_stage(exc: BaseException) -> AIDesignFailureStage:
    category = str(getattr(exc, "category", "provider_error") or "provider_error")
    diagnostics = dict(getattr(exc, "diagnostics", {}) or {})
    status = diagnostics.get("http_status")
    if category in {"authentication_required", "auth_config", "auth_error"}:
        return AIDesignFailureStage.AUTH
    if category in {"model", "model_unavailable"}:
        return AIDesignFailureStage.MODEL
    if category == "configuration_error" and status in {400, 404}:
        return AIDesignFailureStage.MODEL
    if category in {
        "structured_json_parse_error", "response_json_error",
        "structured_empty_response", "structured_output_truncated",
        "structured_output_truncated_before_answer",
    }:
        return AIDesignFailureStage.PARSE
    if category == "quality_validator" or "VISUAL_QUALITY" in str(exc):
        return AIDesignFailureStage.QUALITY_VALIDATOR
    if category in {"schema", "structured_output", "response_schema_error"}:
        return AIDesignFailureStage.SCHEMA
    if category in {"timeout", "offline"}:
        return AIDesignFailureStage.HTTP
    return AIDesignFailureStage.HTTP


def _provider_failure_message(exc: BaseException) -> tuple[str, str, str, str]:
    category = str(getattr(exc, "category", "provider_error") or "provider_error")
    failure_stage = _design_failure_stage(exc).value
    messages = {
        "authentication_required": "Provider 认证失败：需要重新登录。",
        "auth_config": "Provider 认证失败：缺少认证信息。",
        "auth_error": "Provider 认证失败：认证被服务端拒绝。",
        "timeout": "设计请求超时；这不表示登录已失效，可直接重试。",
        "connection": "Provider 传输失败，请检查网络或服务端状态。",
        "transport_error": "Provider 传输失败，请检查网络或服务端状态。",
        "model_unavailable": "Provider 已响应 · 当前模型不可用",
        "model": "Provider 已响应 · 当前模型不可用",
        "configuration_error": "Provider 已响应 · 模型或请求配置不受支持",
        "nonzero_exit": "Provider 进程执行失败。",
        "empty_response": "Provider 进程成功退出但没有返回内容。",
        "structured_json_parse_error": "Provider 已响应 · 设计结构无效",
        "structured_output": "Provider 已响应 · 设计结构无效",
        "schema": "Provider 已响应 · 设计结构无效",
        "quality_validator": "Provider 已响应 · 方案质量不足",
        "rate_limit": "Provider 当前限流，请稍后重试。",
        "rate_limited": "Provider 当前限流，请稍后重试。",
        "not_installed": "未安装当前配置的 Provider CLI。",
        "cancelled": "视觉设计生成已取消。",
    }
    message = messages.get(category, f"Provider 请求失败：{exc}")
    # Model/config failures must surface the server's own answer (HTTP
    # status, error body, requested model id) instead of a generic caption —
    # otherwise a wrong registry id is indistinguishable from an outage.
    if category in {
        "model", "model_unavailable", "configuration_error",
        "server_error", "rate_limited", "rate_limit",
    }:
        diagnostics = dict(getattr(exc, "diagnostics", {}) or {})
        detail_parts = []
        if diagnostics.get("http_status") is not None:
            detail_parts.append(f"HTTP {diagnostics['http_status']}")
        requested_model = str(diagnostics.get("model") or "")
        if requested_model:
            detail_parts.append(f"model={requested_model}")
        raw = str(exc).strip()
        if raw:
            detail_parts.append(raw[:300])
        if detail_parts:
            message = f"{message}（{' · '.join(detail_parts)}）"
    generate_stage = {
        "timeout": "TIMEOUT", "empty_response": "EMPTY_OUTPUT",
        "structured_json_parse_error": "JSON", "response_json_error": "JSON", "schema": "SCHEMA",
        "structured_output": "SCHEMA",
        "quality_validator": "QUALITY",
    }.get(category, "PROCESS")
    return category, failure_stage, message, generate_stage


def _fallback_graph_recipes(
    instruction: str,
    base_recipe: StyleRecipe,
    fonts: Mapping[str, list[str]],
    directions: tuple[ArtDirectionSpec, ...] | None = None,
) -> list[StyleRecipe]:
    def planned_graph(direction: ArtDirectionSpec) -> VisualDesignGraph:
        family = direction.primary_family
        if family == "AMERICAN_COMIC_BURST":
            return comic_burst_graph()
        if family == "MANGA_IMPACT":
            return manga_impact_graph()
        if family == "HALFTONE_SLAM":
            graph = comic_burst_graph()
            graph.name = "Halftone Slam"
            graph.panel_layer.primitive = "CUT_CORNER"
            graph.decoration_layers = [
                item for item in graph.decoration_layers if item.primitive == "HALFTONE"
            ]
            graph.motion_graph.tracks = [
                item for item in graph.motion_graph.tracks if item.target != "rays"
            ]
            return graph.validate()
        if family == "CRT_GLITCH":
            return glitch_graph()
        if family in {"DATA_SCAN", "SIGNAL_LOSS", "CYBER_HUD"}:
            graph = glitch_graph()
            graph.name = ART_DIRECTION_TEMPLATES[family].display_name
            graph.panel_layer.primitive = (
                "NONE" if family == "DATA_SCAN" else
                "TECH_FRAME" if family == "CYBER_HUD" else "RECTANGLE"
            )
            graph.panel_layer.params = {} if family == "DATA_SCAN" else graph.panel_layer.params
            graph.effect_layers = []
            graph.motion_graph.tracks = [
                item for item in graph.motion_graph.tracks if item.target != "glitch"
            ]
            return graph.validate()
        if family == "ACHIEVEMENT_POP":
            return achievement_pop_graph()
        if family == "STREAMER_EMPHASIS":
            return streamer_gaming_graph()
        if family == "CRITICAL_HIT":
            graph = manga_impact_graph()
            graph.name = "Critical Hit"
            graph.panel_layer.primitive = "BADGE"
            graph.decoration_layers = [
                item for item in graph.decoration_layers if item.primitive == "SHARDS"
            ]
            graph.motion_graph.tracks = [
                item for item in graph.motion_graph.tracks if item.target != "speed"
            ]
            return graph.validate()
        if family == "CLEAN_EDITORIAL":
            return clean_subtitle_graph()
        if family == "INDUSTRIAL_BRASS_HUD":
            return industrial_brass_hud_graph()
        if family == "VICTORIAN_MECHANICAL":
            return victorian_mechanical_graph()
        if family == "STEAM_GAUGE_TYPO":
            return steam_gauge_graph()
        return graph_from_style_recipe(base_recipe)

    selected_directions = directions or fallback_art_directions(instruction)
    candidates = [planned_graph(item) for item in selected_directions]
    graphs: list[VisualDesignGraph] = []
    signatures: set[tuple[Any, ...]] = set()
    for graph in candidates:
        _normalize_graph_font(graph, fonts)
        graph.validate()
        signature = structural_signature(graph)
        if signature in signatures:
            continue
        signatures.add(signature)
        graphs.append(graph)
        if len(graphs) == len(selected_directions):
            break
    if len(graphs) < 3:
        # Local keyword variants are deterministic fallbacks, not provider
        # output; only structural duplicates (deduped above) can starve them.
        raise VisualDesignGraphValidationError("A/B/C requires at least three variants")
    return [style_recipe_from_graph(graph) for graph in graphs]


_AI_SECRET_KEYS = {"api_key", "apikey", "authorization", "access_token", "refresh_token", "token", "secret"}
_AI_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(?:sk|xai|AIza|ya29|ghp|glpat)-[A-Za-z0-9._-]{12,}"),
)


def _redact_ai_trace(value: Any, *, key: str = "") -> Any:
    """Keep provider diagnostics useful while excluding credentials and tokens."""
    if str(key).casefold() in _AI_SECRET_KEYS or any(
        token in str(key).casefold() for token in ("api_key", "access_token", "refresh_token", "authorization")
    ):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact_ai_trace(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_ai_trace(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            redacted = value
            for pattern in _AI_SECRET_PATTERNS:
                redacted = pattern.sub("[REDACTED]", redacted)
            return redacted
        return value
    return str(value)


def _persist_ai_design_trace(trace: Mapping[str, Any]) -> str:
    """Write one redacted, inspectable design pipeline record in dev data."""
    payload = json.dumps(
        _redact_ai_trace(dict(trace)), ensure_ascii=False, indent=2, sort_keys=True
    )
    # App-data is the normal destination. Restricted launches (and some
    # packaged repair contexts) can expose it as read-only; retain a local,
    # inspectable trace instead of returning an unusable empty path.
    roots = (studio_data_root(), Path(tempfile.gettempdir()) / "2ByteASR")
    for root in roots:
        try:
            directory = root / "logs" / "ai_design"
            directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = directory / f"design-{stamp}-{int(time.time_ns() % 1_000_000):06d}.json"
            path.write_text(payload, encoding="utf-8")
            try:
                from .build_identity import user_data_root

                public = user_data_root() / "logs" / "ai_design" / path.name
                public.parent.mkdir(parents=True, exist_ok=True)
                public.write_text(payload, encoding="utf-8")
            except OSError:
                pass
            return str(path)
        except OSError:
            continue
    return ""


def request_style_design(
    project: SubtitleProject,
    cue_id: str,
    instruction: str,
    runtime_settings: dict | None = None,
    *,
    deadline_seconds: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
    stage_callback: Callable[[str], None] | None = None,
    vision_frame_path: str | Path | None = None,
    vision_frame_supplier: Callable[[], str | Path | None] | None = None,
) -> AIDesignSuggestion:
    stage_timings: dict[str, float] = {}
    active_stage: AIDesignStage | None = None
    active_started = time.monotonic()

    def transition(stage: AIDesignStage) -> None:
        nonlocal active_stage, active_started
        now = time.monotonic()
        if active_stage is not None:
            stage_timings[active_stage.value] = round(
                stage_timings.get(active_stage.value, 0.0)
                + (now - active_started) * 1000.0,
                3,
            )
        active_stage = stage
        active_started = now
        if stage_callback is not None:
            stage_callback(stage.value)

    def raise_if_cancelled() -> None:
        if cancel_check is not None and cancel_check():
            raise AIProviderError("视觉设计生成已取消。", category="cancelled")

    transition(AIDesignStage.PREPARING_CONTEXT)
    cue_by_id(project, cue_id)  # validate ownership before producing a proposal
    source = str(instruction or "").strip() or "柔和清晰的对白字幕"
    settings = runtime_settings if isinstance(runtime_settings, dict) else {}
    if not settings.get("models"):
        settings = GLOBAL_PROVIDER_REGISTRY.settings()
    else:
        GLOBAL_PROVIDER_REGISTRY.bind(settings)
    recipe = None
    variants: tuple[VisualStyleRecipe, ...] = ()
    rationale = ""
    design_intent = ""
    visual_changes: tuple[str, ...] = ()
    motion_reason = ""
    raw_response: dict[str, Any] = {}
    art_directions: tuple[ArtDirectionSpec, ...] = ()
    quality_scores: tuple[VisualQualityScore, ...] = ()
    provider_succeeded = False
    provider_error_category = ""
    failure_stage = ""
    generate_failure_stage = ""
    repair_attempted = False
    trace: dict[str, Any] = {
        "schema_version": 1,
        "stage": "studio_visual_design",
        "cue_id": str(cue_id),
        "instruction": source,
        "provider": {},
        "raw_provider_responses": [],
        "parsed_json": None,
        "validation_errors": [],
        "repair_response": None,
    }
    request_state = ProviderStateMachine()
    pipeline_status = {
        stage.value: "NOT_RUN" for stage in AIDesignFailureStage
    }
    provider_supports_vision = False
    vision_frame_sent = False
    fonts = available_font_shortlist(limit=18)
    models = settings.get("models", {}) if isinstance(settings, Mapping) else {}
    configured_deadline = None
    if isinstance(models, Mapping):
        configured_deadline = models.get(
            "ai_design_timeout_seconds",
            models.get("polish_timeout_seconds"),
        )
    try:
        total_budget = float(
            deadline_seconds if deadline_seconds is not None else configured_deadline or 45.0
        )
    except (TypeError, ValueError):
        total_budget = 45.0
    total_budget = max(0.1 if deadline_seconds is not None else 5.0, total_budget)
    deadline_monotonic = time.monotonic() + total_budget
    try:
        raise_if_cancelled()
        transition(AIDesignStage.CONNECTING_PROVIDER)
        provider = provider_for_stage(settings, "polish")
        selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
        transport = str(getattr(getattr(provider, "transport", None), "value", getattr(provider, "transport", "")))
        readiness_trace: dict[str, Any] | None = None
        validate_provider = getattr(provider, "validate", None)
        if callable(validate_provider) and str(getattr(getattr(provider, "transport", None), "value", getattr(provider, "transport", ""))) not in {"antigravity_cli", "grok_cli", "codex_cli"}:
            if not selection.credential_ready:
                request_state.advance(
                    ProviderRequestState.UNCONFIGURED,
                    f"{selection.provider} credential missing",
                )
                raise AIProviderError("当前 Provider 尚未配置凭据。", category="authentication_required")
            request_state.advance(
                ProviderRequestState.AUTH_READY,
                f"{selection.service}/{selection.model}",
            )
            remaining_for_probe = max(0.1, deadline_monotonic - time.monotonic())
            status = validate_provider(
                timeout=min(8.0, remaining_for_probe),
                cancel_check=cancel_check,
                use_cache=True,
            )
            readiness_trace = {
                "available": bool(status.available),
                "authenticated": bool(status.authenticated),
                "message": str(status.message or "")[:300],
                "models": list(status.models),
            }
            if not status.authenticated:
                readiness_message = str(status.message or "")
                readiness_timeout = (
                    transport in {"antigravity_cli", "grok_cli"}
                    and bool(status.available)
                    and any(
                        token in readiness_message.casefold()
                        for token in ("timeout", "timed out", "超时")
                    )
                )
                readiness_trace["deferred_to_generate"] = readiness_timeout
                if not readiness_timeout:
                    request_state.advance(
                        ProviderRequestState.AUTH_ERROR if status.available else ProviderRequestState.TRANSPORT_ERROR,
                        readiness_message[:300],
                    )
                    raise AIProviderError(
                        readiness_message or "Provider Session 未就绪",
                        category="authentication_required" if status.available else "connection",
                    )
                # A readiness probe timeout is a timeout of the probe, not
                # proof that the CLI session is unauthenticated. Continue to
                # the real Generate phases so the packaged trace can identify
                # the actual failure stage and preserve successful sessions.
                request_state.advance(
                    ProviderRequestState.AUTH_READY,
                    "readiness probe timeout; real Generate will determine session viability",
                )
            else:
                request_state.advance(
                    ProviderRequestState.SESSION_READY,
                    str(status.message or "")[:300],
                )
        else:
            request_state.advance(ProviderRequestState.AUTH_READY, "real request determines CLI session readiness")
        cue = cue_by_id(project, cue_id)
        profile = _project_style_profile(project, cue_id)
        capabilities_getter = getattr(provider, "capabilities", None)
        provider_manifest = capabilities_getter() if callable(capabilities_getter) else None
        provider_supports_vision = bool(getattr(provider_manifest, "vision", False))
        cli_transport = transport in {"antigravity_cli", "grok_cli"}
        frame_candidate = vision_frame_path
        # CLI transports pass the prompt through ``-p`` argv; a base64 frame
        # exceeds the Windows CreateProcess command-line budget (~32 KiB) and
        # kills the spawn as a generic transport error. CLI requests stay
        # text-only; HTTP providers keep receiving the vision frame.
        frame_allowed = provider_supports_vision and not cli_transport
        if frame_allowed and frame_candidate is None and vision_frame_supplier is not None:
            frame_candidate = vision_frame_supplier()
            raise_if_cancelled()
        frame_data_url = _vision_data_url(frame_candidate) if frame_allowed else ""
        vision_frame_sent = bool(frame_data_url)
        if cli_transport and deadline_seconds is None:
            # CLI agents plan far slower than HTTP; the HTTP design budget
            # must not cap them. Explicit caller deadlines still win.
            try:
                cli_budget = float(
                    (models.get("ai_design_cli_timeout_seconds")
                     if isinstance(models, Mapping) else None) or 300.0
                )
            except (TypeError, ValueError):
                cli_budget = 300.0
            cli_budget = max(5.0, cli_budget)
            if cli_budget > total_budget:
                total_budget = cli_budget
                deadline_monotonic = time.monotonic() + total_budget
        trace["provider"] = {
            "provider_id": str(getattr(provider, "provider_id", "")),
            "model_id": str(getattr(provider, "model", "")),
            "model": str(getattr(provider, "model", "")),
            "transport": transport,
            "effective_timeout_seconds": round(total_budget, 3),
            "request_id": f"{cue_id}:{int(time.time() * 1000)}",
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if readiness_trace is not None:
            trace["provider"]["readiness"] = readiness_trace
        system_prompt = (
            _STYLE_DESIGN_CLI_SYSTEM
            if transport in {"antigravity_cli", "grok_cli"}
            else _STYLE_DESIGN_SYSTEM
        )
        request_context = {
            "instruction": source,
            "cue_text": cue.text,
            **profile,
            "available_fonts": fonts,
            "visual_capability_manifest": visual_capability_manifest(),
            "curated_art_direction_families": art_direction_manifest(),
            "visual_graph_schema": _VISUAL_GRAPH_DESIGN_SCHEMA,
            "semantic_requirements": _visual_graph_semantic_requirements(source),
            "provider_capabilities": {
                "vision": provider_supports_vision,
                "structured_output": bool(getattr(provider_manifest, "structured_output", True)),
                "structured_output_mode": str(
                    getattr(provider_manifest, "structured_output_mode", "JSON_MODE")
                ),
            },
            "need": (
                "先生成 A/B/C 三套语义 ArtDirectionSpec，再分别规划成结构不同、"
                "可由可信原语编译的 VisualDesignGraph V1 JSON"
            ),
        }
        if transport in {"antigravity_cli", "grok_cli"}:
            # CLI transports time out on the full manifests: the compact
            # system contract already fixes the exact graph key list, and the
            # CLI adapter drops the JSON schema, so the user payload only
            # needs the trusted allowlists plus family vocabulary.
            request_context.update({
                "curated_family_vocabulary": _compact_cli_family_vocabulary(),
                "art_direction_spec": {
                    "schema": ART_DIRECTION_SCHEMA,
                    "version": ART_DIRECTION_VERSION,
                    "required_keys": list(_ART_DIRECTION_SPEC_SCHEMA["required"]),
                    "density": ["LOW", "MEDIUM", "HIGH"],
                    "primary_family": sorted(ART_DIRECTION_TEMPLATES),
                },
            })
            request_context.pop("curated_art_direction_families", None)
            request_context.pop("visual_graph_schema", None)
        user_content: object = json.dumps(request_context, ensure_ascii=False)
        if frame_data_url:
            user_content = [
                {"type": "text", "text": str(user_content)},
                {"type": "image_url", "image_url": {"url": frame_data_url}},
            ]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        # Sizes only: the trace never stores prompt text or secrets.
        trace["provider"]["prompt_size_bytes"] = {
            "system": len(system_prompt.encode("utf-8")),
            "user": (
                sum(
                    len(str(part.get("text") or "").encode("utf-8"))
                    for part in user_content
                    if isinstance(part, Mapping)
                )
                if isinstance(user_content, list)
                else len(str(user_content).encode("utf-8"))
            ),
        }
        parsed = None
        last_validation_error: Exception | None = None
        for attempt in range(2):
            raise_if_cancelled()
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise AIProviderError("AI 视觉设计请求超时。", category="timeout")
            transition(AIDesignStage.GENERATING)
            request_state.advance(ProviderRequestState.REQUESTING, f"attempt={attempt + 1}")
            if transport in {"antigravity_cli", "grok_cli"}:
                payload = _cli_two_phase_generate(
                    provider,
                    system_prompt,
                    request_context,
                    frame_data_url=frame_data_url,
                    deadline_monotonic=deadline_monotonic,
                    cancel_check=cancel_check,
                    trace=trace,
                    on_phase=lambda label: request_state.advance(
                        ProviderRequestState.REQUESTING, f"phase={label}"
                    ),
                )
            else:
                payload = provider.structured_complete(
                    messages,
                    _VISUAL_GRAPH_DESIGN_SCHEMA,
                    max_tokens=8192,
                    temperature=0.72,
                    timeout=remaining,
                    cancel_check=cancel_check,
                    stage="studio_visual_design",
                )
            invocation_trace = getattr(provider, "invocation_trace", None)
            if callable(invocation_trace):
                trace["provider"]["invocation"] = invocation_trace()
            pipeline_status[AIDesignFailureStage.AUTH.value] = "PASS"
            pipeline_status[AIDesignFailureStage.HTTP.value] = "PASS"
            request_state.advance(ProviderRequestState.RESPONSE_RECEIVED)
            transition(AIDesignStage.PARSING)
            if not isinstance(payload, Mapping):
                raise AIProviderError(
                    "AI 没有返回 JSON 对象。", category="structured_json_parse_error"
                )
            pipeline_status[AIDesignFailureStage.PARSE.value] = "PASS"
            request_state.advance(ProviderRequestState.PARSE_OK)
            raw_response = copy.deepcopy(dict(payload))
            trace["raw_provider_responses"].append(copy.deepcopy(dict(payload)))
            if attempt == 1:
                # Keep the repair response distinct from the local fallback
                # object built below when the second validation still fails.
                trace["repair_response"] = copy.deepcopy(dict(payload))
            try:
                transition(AIDesignStage.VALIDATING)
                parsed = _parse_design_payload(payload, source, fonts)
                trace["parsed_json"] = {
                    "design_intent": parsed[1],
                    "visual_changes": list(parsed[2]),
                    "motion_reason": parsed[3],
                    "variant_count": len(parsed[0]),
                }
                pipeline_status[AIDesignFailureStage.SCHEMA.value] = "PASS"
                request_state.advance(ProviderRequestState.SCHEMA_OK)
                pipeline_status[AIDesignFailureStage.QUALITY_VALIDATOR.value] = "PASS"
                request_state.advance(ProviderRequestState.QUALITY_OK)
                if repair_attempted:
                    pipeline_status[AIDesignFailureStage.REPAIR.value] = "PASS"
                break
            except Exception as exc:
                last_validation_error = exc
                trace["validation_errors"].append({
                    "attempt": attempt + 1,
                    "stage": "QUALITY_VALIDATOR" if "VISUAL_QUALITY" in str(exc) else "SCHEMA",
                    "message": str(exc),
                })
                validation_stage = (
                    AIDesignFailureStage.QUALITY_VALIDATOR
                    if "VISUAL_QUALITY" in str(exc)
                    else AIDesignFailureStage.SCHEMA
                )
                pipeline_status[validation_stage.value] = "FAIL"
                if attempt:
                    raise AIProviderError(
                        str(exc),
                        category=(
                            "quality_validator"
                            if validation_stage is AIDesignFailureStage.QUALITY_VALIDATOR
                            else "schema"
                        ),
                    ) from exc
                transition(AIDesignStage.REPAIRING)
                repair_attempted = True
                pipeline_status[AIDesignFailureStage.REPAIR.value] = "RUNNING"
                messages.extend([
                    {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            "Your previous design was invalid or insufficiently distinct. "
                            "Return three semantic ArtDirectionSpec objects first, each with a different dominant family, "
                            "then return the three corresponding complete VisualDesignGraph V1 objects. "
                            "Return three complete VisualDesignGraph V1 objects. "
                            "A/B/C must differ in panel, decorations, effects, or MotionGraph structure. "
                            "The user instruction is binding: all three variants stay inside its style direction as "
                            "different sub-styles, and every visual idea the prose declares must exist as a real "
                            "primitive or typography feature (metallic→multi-stop warm gradient, gears→GEARS, "
                            "rivets→RIVETS, gauge→GAUGE, pipes→PIPES, steam→STEAM, multi-outline→>=2 strokes). "
                            "Remove every unknown field and follow the exact key contract from the system message. "
                            "Every object/array container must have the required JSON type and must not be null. "
                            "In particular, textLayer must not contain text, position, rotation, opacity, timing, or animation. "
                            "Remove decoration before adding effects when quality reports OVERDECORATED, and replace "
                            "generic scale/slide/fade with family-specific layered timing when it reports CHEAP_MOTION. "
                            f"Validation error: {exc}"
                        ),
                    },
                ])
                trace["repair_request"] = messages[-1].get("content", "")
                if attempt == 0:
                    trace["repair_response"] = None
        if parsed is None:
            raise AIProviderError(
                str(last_validation_error or "AI 视觉方案校验失败"),
                category="structured_output",
            )
        transition(AIDesignStage.BUILDING_LIVE)
        (
            recipes, design_intent, visual_changes, motion_reason,
            art_directions, quality_scores,
        ) = parsed
        recipe = recipes[0]
        variants = tuple(VisualStyleRecipe.from_style_recipe(item) for item in recipes)
        rationale = f"已通过 {provider.provider_id} 生成并校验三套真实视觉方案。"
        provider_succeeded = True
        pipeline_status[AIDesignFailureStage.FINAL.value] = "PASS"
        request_state.advance(ProviderRequestState.SUCCESS)
    except Exception as exc:
        invocation_trace = getattr(locals().get("provider"), "invocation_trace", None)
        if callable(invocation_trace):
            trace.setdefault("provider", {})["invocation"] = invocation_trace()
        provider_error_category, failure_stage, failure_message, generate_failure_stage = _provider_failure_message(exc)
        pipeline_status[failure_stage] = "FAIL"
        if repair_attempted and pipeline_status[AIDesignFailureStage.REPAIR.value] == "RUNNING":
            pipeline_status[AIDesignFailureStage.REPAIR.value] = "FAIL"
        pipeline_status[AIDesignFailureStage.FINAL.value] = "LOCAL_FALLBACK"
        if request_state.state not in {
            ProviderRequestState.AUTH_ERROR,
            ProviderRequestState.SPAWN_ERROR,
            ProviderRequestState.TRANSPORT_ERROR,
            ProviderRequestState.TIMEOUT,
            ProviderRequestState.MODEL_ERROR,
            ProviderRequestState.PARSE_ERROR,
            ProviderRequestState.SCHEMA_ERROR,
            ProviderRequestState.QUALITY_ERROR,
        }:
            error_state = {
                "cancelled": ProviderRequestState.CANCELLED,
                "authentication_required": ProviderRequestState.AUTH_ERROR,
                "auth_config": ProviderRequestState.AUTH_ERROR,
                "auth_error": ProviderRequestState.AUTH_ERROR,
                "not_installed": ProviderRequestState.SPAWN_ERROR,
                "spawn_error": ProviderRequestState.SPAWN_ERROR,
                "timeout": ProviderRequestState.TIMEOUT,
                "model": ProviderRequestState.MODEL_ERROR,
                "model_unavailable": ProviderRequestState.MODEL_ERROR,
                "structured_json_parse_error": ProviderRequestState.PARSE_ERROR,
                "schema": ProviderRequestState.SCHEMA_ERROR,
                "quality_validator": ProviderRequestState.QUALITY_ERROR,
            }.get(provider_error_category, ProviderRequestState.TRANSPORT_ERROR)
            request_state.advance(error_state, str(exc)[:300])
        transition(AIDesignStage.FAILED)
        if provider_error_category == "cancelled":
            raise AIProviderError(failure_message, category="cancelled") from exc
        transition(AIDesignStage.BUILDING_LIVE)
        recipe = style_recipe_for_prompt(source)
        _normalize_recipe_font(recipe, fonts)
        recipe.validate()
        art_directions = fallback_art_directions(source)
        fallback_recipes = _fallback_graph_recipes(
            source, recipe, fonts, art_directions,
        )
        fallback_graphs = [
            VisualDesignGraph.from_dict(item.visual_graph)
            for item in fallback_recipes
        ]
        repaired_graphs = []
        fallback_scores = []
        for graph, direction in zip(fallback_graphs, art_directions):
            graph, score = validate_and_repair_graph(graph, direction, deadline_ms=40.0)
            repaired_graphs.append(graph)
            fallback_scores.append(score)
        fallback_recipes = [style_recipe_from_graph(graph) for graph in repaired_graphs]
        quality_scores = tuple(fallback_scores)
        recipe = fallback_recipes[0]
        variants = tuple(
            VisualStyleRecipe.from_style_recipe(item) for item in fallback_recipes
        )
        raw_response = {
            "provider_error": str(exc),
            "provider_error_category": provider_error_category,
            "failure_stage": failure_stage,
            "generate_failure_stage": generate_failure_stage,
            "pipeline_status": dict(pipeline_status),
            "http_diagnostics": get_last_llm_response_diagnostics(),
            "fallback": recipe.to_dict(),
        }
        rationale = (
            f"{failure_message}\n"
            "Provider 未成功。可点击「使用本地备选」，或重试 Provider。"
        )
    trace["final"] = {
        "provider_succeeded": provider_succeeded,
        "provider_error_category": provider_error_category,
        "failure_stage": failure_stage,
        "generate_failure_stage": generate_failure_stage,
        "repair_attempted": repair_attempted,
        "pipeline_status": dict(pipeline_status),
        "fallback_used": not provider_succeeded,
        "provider_state": request_state.state.value,
    }
    trace["provider_state_machine"] = list(request_state.history)
    trace["fallback_recipe"] = recipe.to_dict() if recipe is not None and not provider_succeeded else None
    trace_path = _persist_ai_design_trace(trace)
    route = route_recipe(recipe)
    if route.engine == "remotion" and recipe.engine == "native":
        recipe.engine = "remotion"
    if not variants:
        visual = VisualStyleRecipe.from_style_recipe(recipe)
        variants = tuple(visual_design_variants(source, visual))
    now = time.monotonic()
    if active_stage is not None:
        stage_timings[active_stage.value] = round(
            stage_timings.get(active_stage.value, 0.0)
            + (now - active_started) * 1000.0,
            3,
        )
    raw_response.setdefault("_studio_telemetry", {})
    if isinstance(raw_response["_studio_telemetry"], dict):
        raw_response["_studio_telemetry"].update(
            {
                "deadline_seconds": total_budget,
                "provider_succeeded": provider_succeeded,
                "provider_error_category": provider_error_category,
                "failure_stage": failure_stage,
                "generate_failure_stage": generate_failure_stage,
                "pipeline_status": dict(pipeline_status),
                "repair_attempted": repair_attempted,
                "provider_supports_vision": provider_supports_vision,
                "vision_frame_sent": vision_frame_sent,
                "stage_timings_ms": dict(stage_timings),
                "trace_path": trace_path,
            }
        )
    return AIDesignSuggestion(
        str(cue_id),
        recipe,
        rationale,
        tuple(variants),
        design_intent,
        visual_changes,
        motion_reason,
        raw_response,
        provider_succeeded,
        provider_error_category,
        dict(stage_timings),
        tuple(art_directions),
        tuple(quality_scores),
        failure_stage,
        dict(pipeline_status),
        repair_attempted,
    )


_STYLE_REVISION_SYSTEM = """
You are revising ONE kinetic-subtitle design. The user already approved a direction; treat the previous ArtDirectionSpec + VisualDesignGraph as the base and apply ONLY the requested change as a PATCH — do not redesign from zero and do not change parts the feedback did not mention. Keep the same primary_family unless the feedback explicitly asks for a different direction. Return ONLY compact JSON with keys: revision_notes (one short sentence, Chinese), direction (revised ArtDirectionSpec), variant (the full revised VisualDesignGraph V1 — the complete graph, never a diff). Use only trusted primitives; font.family must come from available_fonts; keep the readable hold; declared visual ideas must materialize as real primitives.
""".strip()

_VISUAL_GRAPH_REVISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["revision_notes", "direction", "variant"],
    "properties": {
        "revision_notes": {"type": "string", "minLength": 1, "maxLength": 240},
        "direction": _ART_DIRECTION_SPEC_SCHEMA,
        "variant": _VISUAL_GRAPH_SCHEMA,
    },
}


def request_style_revision(
    project,
    cue_id: str,
    base_instruction: str,
    feedback: str,
    previous_direction: ArtDirectionSpec | None,
    previous_graph: VisualDesignGraph | Mapping | None,
    settings: Mapping[str, object],
    *,
    cancel_check=None,
    stage_callback=None,
) -> tuple[VisualStyleRecipe, ArtDirectionSpec, str]:
    """One-round PATCH revision of a single AI design variant (“微调设计”).

    Returns ``(revised_recipe, revised_direction, revision_notes)``. Raises
    ``RuntimeError`` with a user-facing message on provider or validation
    failure — callers keep the previous version untouched.
    """
    def raise_if_cancelled() -> None:
        if cancel_check is not None and cancel_check():
            raise AIProviderError("视觉设计生成已取消。", category="cancelled")

    if stage_callback is not None:
        stage_callback(AIDesignStage.GENERATING.value)
    provider = provider_for_stage(settings, "polish")
    transport = str(getattr(getattr(provider, "transport", None), "value", getattr(provider, "transport", "")))
    try:
        if transport not in {"antigravity_cli", "grok_cli", "codex_cli"}:
            provider.validate(timeout=8.0, use_cache=True)
    except BaseException as exc:
        message, _label, _hint, _stage = _provider_failure_message(exc)
        raise RuntimeError(f"微调失败：{message}") from exc
    cue = cue_by_id(project, cue_id)
    previous_graph_payload = (
        previous_graph.to_dict() if isinstance(previous_graph, VisualDesignGraph)
        else dict(previous_graph) if isinstance(previous_graph, Mapping)
        else {}
    )
    if not previous_graph_payload:
        raise RuntimeError("微调失败：当前方案没有可用的 VisualDesignGraph。")
    # Font enumeration is a heavyweight native call; only reach it after the
    # cheap fail-fast guards have passed.
    fonts = available_font_shortlist()
    previous_direction_payload = (
        previous_direction.to_dict() if previous_direction is not None else {}
    )
    request_context = {
        "base_instruction": str(base_instruction or ""),
        "user_feedback": str(feedback or "").strip(),
        "cue_text": cue.text,
        "available_fonts": fonts,
        "previous_direction": previous_direction_payload,
        "previous_graph": previous_graph_payload,
        "capability_manifest": visual_capability_manifest(),
        "need": "PATCH：只修改用户反馈提到的部分，输出完整修订后的 VisualDesignGraph V1",
    }
    if transport in {"antigravity_cli", "grok_cli"}:
        request_context.pop("capability_manifest", None)
        request_context["curated_family_vocabulary"] = _compact_cli_family_vocabulary()
    messages = [
        {"role": "system", "content": _STYLE_REVISION_SYSTEM},
        {"role": "user", "content": json.dumps(request_context, ensure_ascii=False)},
    ]
    models = settings.get("models", {}) if isinstance(settings, Mapping) else {}
    cli_transport = transport in {"antigravity_cli", "grok_cli"}
    default_budget = 300.0 if cli_transport else 45.0
    budget_key = "ai_design_cli_timeout_seconds" if cli_transport else "ai_design_timeout_seconds"
    try:
        budget = float(models.get(budget_key) or default_budget)
    except (TypeError, ValueError):
        budget = default_budget
    raise_if_cancelled()
    if stage_callback is not None:
        stage_callback(AIDesignStage.PARSING.value)
    try:
        payload = provider.structured_complete(
            messages, _VISUAL_GRAPH_REVISION_SCHEMA,
            max_tokens=8192, temperature=0.4, timeout=max(10.0, budget),
            stage="studio_visual_revision",
        )
    except BaseException as exc:
        message, _label, _hint, _stage = _provider_failure_message(exc)
        raise RuntimeError(f"微调失败：{message}") from exc
    raise_if_cancelled()
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        direction = ArtDirectionSpec.from_dict(dict(payload.get("direction") or {}))
        graph = VisualDesignGraph.from_dict(dict(payload.get("variant") or {}))
        _normalize_graph_font(graph, fonts)
        graph.validate()
        graph, _quality = validate_and_repair_graph(graph, direction, deadline_ms=40.0)
        validate_graph_for_direction(graph, direction)
        validate_graph_matches_instruction(
            f"{base_instruction} {feedback}", direction, graph,
        )
        cue_duration_ms = max(1, int(cue.end_ms) - int(cue.start_ms))
        CompiledLiveScene.compile(graph, cue_duration_ms=cue_duration_ms)
    except (TypeError, ValueError, VisualDesignGraphValidationError) as exc:
        raise RuntimeError(f"微调结果未通过校验：{str(exc)[:220]}") from exc
    notes = str(payload.get("revision_notes") or "").strip()
    return style_recipe_from_graph(graph), direction, notes


def visual_design_variants(prompt: str, primary: VisualStyleRecipe | None = None) -> list[VisualStyleRecipe]:
    """Return three validated visual directions without touching project state."""
    base = primary or VisualStyleRecipe.from_style_recipe(style_recipe_for_prompt(prompt))
    base.validate()
    variants = [copy.deepcopy(base)]
    text = str(prompt or "").casefold()
    if base.engine_requirement == "advanced":
        fonts = available_font_shortlist()
        serif = _font_fallback(fonts, "serif")
        handwriting = _font_fallback(fonts, "handwriting")
        sans = _font_fallback(fonts, "chinese_sans")
        alt = copy.deepcopy(base)
        minimal = copy.deepcopy(base)
        if any(token in text for token in (
            "1930s", "橡皮管", "胶片", "复古", "retro", "rubber hose",
            "old cinema", "黑白",
        )):
            alt.name = "Old Cinema Title"
            alt.typography.update({"fontFamily": serif, "fontSize": 58, "bold": True})
            alt.fill = {"type": "solid", "color": "#FFFFE8BE"}
            alt.strokes = [{"color": "#FF171513", "width": 4.5}]
            alt.background = {
                "enabled": True, "type": "film_card", "fill": "#E8181715", "color": "#E8181715",
                "gradient": {"colors": ["#F02B2822", "#E8131210"], "angle": 90}, "opacity": 0.94,
                "padding_x": 32, "padding_y": 18, "radius": 3,
                "border": {"color": "#FFE7D09D", "width": 2},
                "shadow": {"color": "#88000000", "offset_x": 3, "offset_y": 6, "blur": 10},
                "texture": {"type": "film_grain", "opacity": 0.22, "scale": 1.0, "seed": 1931},
                "transform": {"rotation": 0.6, "scale": 100, "offset_x": 0, "offset_y": 0},
                "marks": ["film_perforation"],
            }
            alt.glow = {}
            alt.motion = MotionRecipe(
                entrance={"type": "overshoot", "duration_ms": 320, "amplitude": 18, "direction": "up"},
                hold={"type": "film_gate", "amplitude": 1.0, "frequency": 8.0},
                exit={"type": "fade", "duration_ms": 190},
            )
            alt.ass = ASSRecipe(True, [{"name": "fad", "values": [180, 160]}])
            minimal.name = "Manga Vintage"
            minimal.typography.update({"fontFamily": handwriting, "fontSize": 60, "bold": True})
            minimal.fill = {"type": "solid", "color": "#FFE7E3D9"}
            minimal.strokes = [
                {"color": "#FF111111", "width": 3.0},
                {"color": "#FF66615A", "width": 1.0},
            ]
            minimal.shadow = {"color": "#FF111111", "distance": 5, "offset_x": 5, "offset_y": 3}
            minimal.motion = MotionRecipe(
                entrance={"type": "rotate", "duration_ms": 220, "rotation": -3},
                hold={"type": "boil", "amplitude": 1.4, "frequency": 9.0},
                exit={"type": "scale", "duration_ms": 150},
            )
            minimal.ass = ASSRecipe(True, [{"name": "frz", "value": -1.2}, {"name": "fad", "values": [80, 120]}])
        elif any(token in text for token in ("手写", "便签", "纸", "handwritten", "paper")):
            alt.name = "Unfolded Note"
            alt.typography.update({"fontFamily": handwriting, "fontSize": 58, "bold": True})
            alt.fill = {"type": "solid", "color": "#FF4A3428"}
            alt.strokes = [{"color": "#FFFFD67A", "width": 2.0}]
            alt.background = {"enabled": True, "color": "#F4FFE4A6", "marks": ["paper_strip"]}
            alt.motion = MotionRecipe(
                entrance={"type": "slide_right", "duration_ms": 300, "unfold": True},
                hold={"type": "subtle_float"},
                exit={"type": "wipe_out", "duration_ms": 180},
            )
            alt.ass = ASSRecipe(True, [{"name": "move", "values": [820, 1030, 960, 1030, 0, 300]}])
            minimal.name = "Pinned Memo"
            minimal.typography.update({"fontFamily": sans, "fontSize": 54, "bold": True})
            minimal.fill = {"type": "solid", "color": "#FF3C2A22"}
            minimal.strokes = [{"color": "#FFFFF0C8", "width": 1.2}]
            minimal.background = {"enabled": True, "color": "#EEFFD36A", "marks": ["tape"]}
            minimal.motion = MotionRecipe(
                entrance={"type": "rotate_in", "duration_ms": 240, "rotation": -2},
                hold={"type": "wiggle", "amplitude": 0.8},
                exit={"type": "slide_out", "duration_ms": 180},
            )
            minimal.ass = ASSRecipe(True, [{"name": "frz", "value": -1.5}, {"name": "fad", "values": [120, 120]}])
        else:
            alt.name = "Neon Terminal"
            alt.typography.update({"fontFamily": sans, "fontSize": 58, "bold": True})
            alt.fill = {"type": "linear-gradient", "angle": 90, "stops": [
                {"position": 0.0, "color": "#FF20D9FF"},
                {"position": 0.5, "color": "#FFFF4DB8"},
                {"position": 1.0, "color": "#FFFFE45E"},
            ]}
            alt.strokes = [
                {"color": "#FF20D9FF", "width": 4.5},
                {"color": "#FFFF4DB8", "width": 1.5},
            ]
            alt.motion = MotionRecipe(
                entrance={"type": "glitch_reveal", "duration_ms": 260},
                hold={"type": "glitch_micro", "period_ms": 1500},
                exit={"type": "wipe_out", "duration_ms": 160},
            )
            alt.ass = ASSRecipe(True, [{"name": "blur", "value": 0.6}, {"name": "fad", "values": [90, 110]}])
            alt.decorations = [{"type": "side_line", "color": "#FF20D9FF", "opacity": 0.55, "size": 12}]
            minimal.name = "Signal Break"
            minimal.typography.update({"fontFamily": sans, "fontSize": 54, "bold": True})
            minimal.fill = {"type": "solid", "color": "#FFB9FFF7"}
            minimal.strokes = [{"color": "#FFFF3D9A", "width": 3.0}]
            minimal.glow = {"color": "#FF20D9FF", "radius": 8, "strength": 0.55, "opacity": 0.42}
            minimal.motion = MotionRecipe(
                entrance={"type": "slide_left", "duration_ms": 190},
                hold={"type": "micro_jitter", "amplitude": 1.2},
                exit={"type": "scale_down", "duration_ms": 130},
            )
            minimal.ass = ASSRecipe(True, [{"name": "frz", "value": 0.8}, {"name": "fad", "values": [60, 80]}])
        alt.validate()
        variants.append(alt)
        minimal.validate()
        variants.append(minimal)
    else:
        alt = copy.deepcopy(base)
        alt.name = "Clean Hold"
        alt.motion = MotionRecipe(entrance={"preset": "fade", "duration": 180}, hold={}, exit={"preset": "fade", "duration": 140})
        alt.validate()
        variants.append(alt)
        soft = copy.deepcopy(base)
        soft.name = "Soft Emphasis"
        soft.motion = MotionRecipe(entrance={"preset": "soft_pop", "duration": 180}, hold={}, exit={})
        soft.validate()
        variants.append(soft)
    return variants[:3]


# ---------------------------------------------------------------------------
# Web visual themes (2byte.web-visual-theme v1)
# ---------------------------------------------------------------------------

@dataclass
class AIWebThemeSuggestion:
    """One validated web theme plus its provenance and diagnostics."""

    theme: dict[str, Any]
    source: str = "ai"
    message: str = ""
    trace_path: str = ""
    provider: str = ""
    elapsed_seconds: float = 0.0
    request_id: str = ''
    model: str = ''
    brief: dict = field(default_factory=dict)
    concepts: list = field(default_factory=list)
    selected_concept_id: str = ''
    quality: dict = field(default_factory=dict)
    render_evidence: dict | None = None
    repair_count: int = 0



_WEB_THEME_CONTRACT_SYSTEM = """你是顶级的游戏化字幕动效设计师兼场景美术，擅长 HTML+CSS 动效（Balatro、弹幕、卡牌、复古 CRT、老虎机、街机等）。
任务：为视频字幕设计一个"网页视觉主题"。直接按下方分节格式输出，不要 JSON、不要把整个输出包进代码围栏、不要任何解释或前后缀。

===NAME===
（主题短名）
===CONCEPT===
（设计概念+实现承诺清单。**每个点名物件后必须标注实现它的类名，格式如：
"三格老虎机卷轴 .reel；红黑筹码堆 .chips；小丑帽角标 .hat；金币光扫 .coin-sweep"。
类名会被程序与 HTML/CSS 逐一对照——缺一个直接拒收重写。**）
===PALETTE===
primary=#RRGGBB secondary=#RRGGBB background=#RRGGBB accent=#RRGGBB text=#RRGGBB
===APPEARANCE===
fontFamily="字体A", "字体B", monospace
fontSize=58
color=#RRGGBB
strokeColor=#RRGGBB
strokeWidth=3.2
letterSpacing=1
===STAGE_HTML===
（环境层 HTML 原文，直接写标签）
===STAGE_CSS===
（环境层 CSS 原文）
===CUE_HTML===
（字幕层 HTML 模板原文，必须包含 {{words}} 或 {{text}} 占位符，可含 {{speaker}}）
===CUE_CSS===
（字幕层 CSS 原文）
===NOTES===
（给用户的一句话说明）

十个分节必须全部出现（顺序不限）；HTML/CSS 直接写原文，无需任何转义。

创作自由度（第一原则）：
- 用户描述是唯一蓝图。用户点名或风格词暗示的物件要大胆展开成真实场景元素（老虎机→三格卷轴/拉杆/跑马灯；小丑牌→小丑帽/筹码堆；HUD→血条/准星/仪表），宁可多不可缺。
- 构图、物件、动画形式没有任何预设限制；避免"圆角卡片+四散方块粒子+斜向光带"这类通用套路，除非用户点名。
- 体积预算：每段 HTML ≤ 8KB、每段 CSS ≤ 16KB——元素丰富优先，场景物件值得用足预算。

高级感设计规范（二十七轮新增——"物件存在"不等于"好看"；扁平几何件/平涂色块=失败，
用户实测反馈："很简单的字幕框和描边颜色，单调且难看"）：
A. 分层景深：场景至少三层纵深——背景氛围层（大范围低对比渐变+暗角 vignette）、
   中景装置层、前景字幕主体层；各层透明度/模糊度（filter: blur）明显不同，
   前景最实、中景次之、氛围最虚。禁止所有物件同一透明度平面排布。
B. 辉光体系（**克制律**）：辉光是调味不是主菜——全画面只允许 1-2 处强辉光
   （核心装置或文字），其余物件用形状+边线+微弱 drop-shadow（α≤0.35）成立。
   "每个物件都在发光"=科技 HUD 俗艳感（用户实测"死亡搁浅变钢铁侠"）。
   至少一处 radial-gradient 氛围光斑打在字幕带附近（低强度）。
C. 材质与细节：底板与装置禁止平涂纯色——用 linear/radial/conic 渐变叠层、
   inset box-shadow 内描边/倒角、repeating-linear-gradient 微纹理（拉丝/扫描线/
   刻度/网格）；金属件用 conic-gradient 或多 stop 线性渐变做高光扫过。
D. 装置具象化：CONCEPT 点名的每个物件必须"像那个东西"，不是抽象几何——
   手印要有五指轮廓（clip-path 多边形或多个子元素拼形）；传感器要有伞骨/
   关节/探头的结构细节；腕环要有断口/刻度/铆钉。"一个圆圈+三根棍"=失败。
E. 尺寸戏剧性：核心装置 8-20u（1080p 下约 96-240px），特效字幕模式下集中在
   字幕带；全是小装饰=没有视觉锚点。字幕底板是最大视觉主体（宽度约 40%-80% 舞台）。
F. 色彩层次：主色相 ≤3 个，但每个色相要有 ≥3 档明度渐变（深-中-亮），
   高饱和点缀色只用于指示灯/高光/关键描边；避免整体低饱和灰蒙蒙。
G. 海报帧意识：入场完成的定格帧必须达到"海报级"构图——装置+底板+文字+辉光
   全部就位、有明确视觉重心；入场动画就是把这幅画"演"出来，而不是元素淡入。
   装置的视觉存在感要强（对比清晰、边界分明），叠在真实视频画面上依然醒目——
   弱透明度小几何件在视频上等于不存在。
H. **色彩比例铁律 70/25/5（二十八轮，用户实测"大元素显俗/死亡搁浅变钢铁侠"）**：
   70% 中性暗色（炭黑/枪灰/深流体色）铺底板与氛围；25% 中间调（冷灰蓝/做旧金属）
   做结构件；**高饱和点缀色（金橙/电蓝/品红）总量 ≤5%，只允许出现在小尺寸装置、
   细线、指示灯上**。大面积（底板/大底衬/粗描边）出现高饱和金属渐变=俗艳拒改。
   参考死亡搁浅本色：黑（BT）+灰（装备）是身体，金色（chiral）只是脉。
I. **质感优先于发光**：高级感来自材质与工艺而不是亮度——底板用多层暗渐变
   （深黑→炭灰）+微纹理（噪点/扫描线/织物/磨损）叠出"实体感"；金属件做旧
   （高光窄、饱和度低）；流体/焦油类底用 conic/radial 暗纹理+边界高光线。
   电弧、大面积发光边框、彩虹 conic 金属=廉价科幻 HUD，禁止。

技术契约（违反会被拒收）：
1. 结构根：环境层写 .wt-stage 的子元素；字幕层写 .wt-cue 的子元素。两层都是绝对定位全屏舞台（1920x1080 基准）。
2. 占位符：{{text}}=整句文本；{{words}}=逐字 span（推荐，做逐字入场）；{{speaker}}=说话人（为空时用 .tag:empty 隐藏）。
   **{{words}} 必须直接放在行容器（如 .line）里——绝不要再包一层 .wt-w 或任何 span（嵌套双重渲染=糊字，直接拒收）。**
3. 字体 token（必须消费）：文字样式必须写 font-family: var(--wt-font); font-size: var(--wt-size)。
   颜色自由：用主题自带配色（渐变/纯色皆可），也可混用 var(--wt-color)/var(--wt-stroke)（描边建议 text-shadow 八向或 drop-shadow filter）。
4. ===APPEARANCE=== 的 fontFamily 写完整字体栈：像素/复古风首选 "Cubic 11", "俐方体11号", "Cascadia Mono", "Consolas", monospace；
   圆润风 "Microsoft YaHei UI", "PingFang SC", sans-serif；书法 "KaiTi", "STKaiti", serif。fontSize 48-72；strokeWidth 2.5-4.5。
5. 尺寸单位：一切 px 尺寸写成 calc(N * var(--wt-u))（1u = 1080p 下 12px），随分辨率缩放；百分比也可。
6. 动画：正常写 CSS @keyframes + animation（infinite 循环、负延迟相位都可以）；运行时会精确驱动，无需顾虑播放机制。
   入场：0s 开始的 animation；出场：animation-delay: calc(var(--wt-dur) - 0.4s)（--wt-dur 是字幕时长秒数）；两者可逗号并列在同一元素。环境层=持续氛围，字幕层=入场/出场/逐字。
   **时间轴铁律（程序核验，违反拒收）**：字幕的入场/出场/逐字动画都是一次性（finite，播放一次后停在末态）；
   infinite 只允许用在场景物件的环境动效（灯珠/筹码/帽子/卷轴…）；.wt-text/.wt-w 文字层绝不允许 infinite；
   .wt-cue 框本体直挂的 infinite 必须是慢周期（≥2.5s 呼吸/漂浮）；CUE_CSS 必须至少引用一次 var(--wt-dur)
   （出场锚定字幕时长——否则 3 秒字幕里 1 秒动画会循环 3 次）。
7. 环境层全程叠加在视频上：必须低调（低不透明度/边缘化），不得大面积遮挡画面主体；字幕主体设计感放 cue 层。
8. 安全白名单：HTML 只允许结构标签 div/span/br/i/b/em/strong 与 SVG（形状/渐变/滤镜）；禁止 script、事件属性。
   **CSS 括号必须严格配对（程序核验）**——少一个右括号会让浏览器把后续声明整段丢弃（如 animation 被吞=元素永久隐形）；
   SVG 必须带 viewBox 且 path 坐标落在 viewBox 内（否则图形被裁剪不可见）。
   CSS 禁止：@import、url() 外链（url(#内部引用) 允许）、expression、javascript:。所有 @keyframes 名字必须以 wt- 开头。
9. 舞台留出安全边距（四边 ≥ 5%）。粒子类小物件起点放框外/文字行外且初始 opacity:0——不得压字。

硬性底线（缺任何一项会被拒收重写）：
1. 文字永远是主角：对比强、可读、有厚重描边或投影；
2. cue 层有"入场动画"（transform 位移/旋转，不只是淡入）与"出场动画"（同元素第二个 animation，delay 用 calc(var(--wt-dur) - Ns)）；
3. stage 层至少一个 infinite 循环氛围动画；
4. 逐字入场：{{words}} 的 .wt-w 用 nth-child 阶梯 animation-delay（约每字 +0.04s）；
5. CONCEPT 点名（含类名标注）的每个物件都有对应 HTML 元素与专属动画——程序逐一核验；
6. **入场/出场必须与装置物理联动且机制独特**（最重要的 motion 要求）：禁止"底板上移弹入+
   逐字左→右弹"这种通用套路。入场机制要和 CONCEPT 的装置绑定，例如：拉杆下压→卷轴狂转→
   定格→字幕砸出；筹码从画面顶抛落堆叠成底板；机柜从侧面滑入展开灯串逐格点亮；字幕被光束
   扫描显影；碎片从四周飞来拼合成框。出场同样收束（卷轴倒转吸回/灯串熄灭下滑/筹码被收走）。
   逐字动画也别只会左→右：可逐字从卷轴滚出/随灯珠节奏闪现/弹性挤压弹跳。
7. 字幕主体（状态条/卡牌/底板）本身必须有入场与出场动画，不只是文字动；
7. **透明度分治（重要）**：舞台全屏层（html/body/.wt-stage）绝不铺不透明背景——视频画面必须
   透出来，氛围用 rgba alpha ≤ 0.25 的叠加；但**字幕框/状态条/机柜底板（cue 层物件）必须
   结实**：底色 rgba alpha ≥ 0.6 或实底——只有用户点名"玻璃/透明框"时才做通透底板。
8. **场景丰富度硬指标（程序核验）**：CONCEPT 至少承诺 4 个具体场景物件类（排除
   .wt-w/.tag/.line/.plate 等通用名），其中至少 2 个的 CSS 带 infinite 持续动画
   （卷轴滚动/灯牌闪烁/机柜灯/跑马灯…）。物件太少=拒收。
9. **底板质感硬指标（程序核验，二十七轮）**：字幕底板/状态条（plate 类选择器）的
   背景禁止平涂纯色/单一 rgba——必须用渐变（linear/radial/conic）或
   repeating-* 微纹理叠出材质，否则整个画面"只是个描边框"（用户实测单调难看）。
   用户点名玻璃/透明框时豁免。

强烈建议（形式完全自由，用贴合主题的物件实现，拒绝套路化）：
- 入场爆点物件（卷轴转动/筹码抛洒/灯串点亮/帽子甩入…）与出场收束动画；
- 持续微动的环境细节（跑马灯/漂浮金币/指针抖动/尘埃——形态贴题即可，不要通用方块粒子）；
- 渐变文字用 background-clip:text；至少一处 radial-gradient 光晕或 vignette 聚焦字幕；
- 同一风格词连续生成必须在配色、构图、物件、入场方式上明显不同（长得一样=失败）。
"""


_WEB_THEME_STALL_SECONDS = 120.0


def request_web_theme_design(project, cue_id, instruction, runtime_settings=None, *,
        deadline_seconds=None, cancel_check=None, stage_callback=None, on_stream_text=None,
        effect_scope='subtitle', request_id='', render_validator=None,
        stage_event_callback=None, resume_design=None, concepts_only=False, reference_frames=(),
        raw_user_prompt=None,ledger_root=None,candidate_cancel_check=None):
    if resume_design and any(c.get('creative_version') for c in resume_design.get('concepts',[])):
        from .caption_creative_pipeline import resume_authored
        return resume_authored(resume_design,instruction,render_validator=render_validator,raw_user_prompt=raw_user_prompt)
    if not resume_design:
        from .caption_creative_pipeline import request_creative_options
        from .provider_registry import GLOBAL_PROVIDER_REGISTRY
        return request_creative_options(project,cue_id,instruction,runtime_settings or GLOBAL_PROVIDER_REGISTRY.settings(),
            request_id=request_id,cancel_check=cancel_check,stage_callback=stage_callback,reference_frames=reference_frames,
            raw_user_prompt=raw_user_prompt,ledger_root=ledger_root,deadline_seconds=deadline_seconds,
            on_stream_text=on_stream_text,stage_event_callback=stage_event_callback,effect_scope=effect_scope,
            candidate_cancel_check=candidate_cancel_check)
    from .web_theme_compiler import compile_theme
    return compile_theme(project,cue_id,instruction,runtime_settings,
        deadline_seconds=deadline_seconds,cancel_check=cancel_check,stage_callback=stage_callback,
        on_stream_text=on_stream_text,effect_scope=effect_scope,request_id=request_id,
        render_validator=render_validator,stage_event_callback=stage_event_callback,resume_design=resume_design,
        concepts_only=concepts_only,reference_frames=reference_frames)


def refine_web_theme_design(
    theme: Mapping[str, Any],
    instruction: str,
    *,
    cue_text: str = "",
    speaker_name: str = "",
    runtime_settings: dict | None = None,
    deadline_seconds: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
    stage_callback: Callable[[str], None] | None = None,
    on_stream_text: Callable[[str], None] | None = None,
    reference_frames=(),
    design_version: int = 1,
    art_revision: bool = False,
    baseline_theme=None,
    locked_paths=(),
) -> AIWebThemeSuggestion:
    """Iteratively refine an EXISTING web theme from a natural-language ask.

    Much lighter than full generation: the current theme rides along as
    sections and the model edits it. On any failure the ORIGINAL theme is
    returned (source="refine_failed") — never an unrelated built-in.
    """
    from .web_theme import WebThemeDocument, WebThemeValidationError, parse_web_theme_sections

    def progress(stage: str) -> None:
        if stage_callback is not None:
            stage_callback(stage)

    started = time.monotonic()
    original = WebThemeDocument.from_dict(dict(theme)).to_dict()
    from .theme_revision_constraints import capture_constraints,enforce_constraints
    constraints=capture_constraints(original,baseline_theme,locked_paths)
    from .theme_design_preservation import PRESERVATION_DIRECTION,SURFACE_DIRECTION,protect_structure,validate_surface_revision
    if art_revision:constraints=protect_structure(original,constraints)
    ask = str(instruction or "").strip()
    if not ask:
        return AIWebThemeSuggestion(
            theme=original, source="refine_failed",
            message="请先输入修改要求（例如：字体换成楷体，主色改成红色）。",
            trace_path="", provider="", elapsed_seconds=0.0,
        )
    settings = copy.deepcopy(runtime_settings or GLOBAL_PROVIDER_REGISTRY.settings())
    models = settings.get("models", {}) if isinstance(settings, Mapping) else {}
    try:
        budget = float(
            deadline_seconds if deadline_seconds is not None
            else models.get("ai_design_cli_timeout_seconds", models.get("ai_design_timeout_seconds"))
            or 180.0
        )
    except (TypeError, ValueError):
        budget = 180.0
    # 提前定义：异常可能发生在 try 内任何位置（凭据/validate 阶段早于生成循环）。
    flow_state = {"last_beat": time.monotonic(), "stall_triggered": False}
    stall_deadline_seconds = _WEB_THEME_STALL_SECONDS

    def sections_of(payload: Mapping[str, Any]) -> str:
        palette = payload.get("palette") or {}
        palette_text = " ".join(
            f"{key}={value}" for key, value in palette.items()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(value))
        )
        own = payload.get("appearance") if isinstance(payload.get("appearance"), Mapping) else {}
        appearance_lines = [
            f"{key}={value}" for key, value in own.items() if str(value).strip()
        ]
        appearance_text = "\n".join(appearance_lines)
        motion_text = ('===MOTION_SPEC===\n'+json.dumps(payload['motionSpec'],ensure_ascii=False)+'\n') if payload.get('motionSpec') else ''
        return (
            f"===NAME===\n{payload.get('name', '')}\n"
            f"===CONCEPT===\n{payload.get('concept', '')}\n"
            f"===PALETTE===\n{palette_text}\n"
            f"===APPEARANCE===\n{appearance_text}\n"
            f"===STAGE_HTML===\n{payload.get('stageHtml', '')}\n"
            f"===STAGE_CSS===\n{payload.get('stageCss', '')}\n"
            f"===CUE_HTML===\n{payload.get('cueHtml', '')}\n"
            f"===CUE_CSS===\n{payload.get('cueCss', '')}\n"
            f"{motion_text}"
            "===NOTES===\n历史说明仅在本地留档；只遵循本次要求与独立用户锁。"
        )

    trace: dict[str, Any] = {
        "schema_version": 1,
        "stage": "studio_web_theme_refine",
        "instruction": ask,
        "provider": {},
        "raw_provider_responses": [],
        "validation_errors": [],
        "web_theme_source": "",
        "revision_kind": "art_revision" if art_revision else "directed_repair",
        "before_theme": original,
        "user_constraints": constraints,
    }
    provider_name = ""
    refined: dict[str, Any] | None = None
    message = ""
    try:
        progress("CONNECTING_PROVIDER")
        provider = provider_for_stage(settings, "polish")
        provider_name = str(getattr(provider, "provider_id", "") or "")
        selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
        if not selection.credential_ready:
            raise AIProviderError("当前 Provider 尚未配置凭据。", category="authentication_required")
        validate_provider = getattr(provider, "validate", None)
        if callable(validate_provider) and str(getattr(getattr(provider, "transport", None), "value", getattr(provider, "transport", ""))) not in {"antigravity_cli", "grok_cli", "codex_cli"}:
            validate_provider(timeout=8.0, cancel_check=cancel_check, use_cache=True)
        user_prompt = (
            f"下面是当前网页视觉主题的完整原文。请按用户的修改要求编辑它，"
            f"然后原样输出修改后的完整主题（十个 ===分节=== 全部保留，含 ===APPEARANCE===）。\n"
            f"未被要求修改的部分必须逐字保留原文；只改动与修改要求相关的部分。\n"
            f"用户改字体/字号/颜色时，改 ===APPEARANCE=== 分节对应键即可（不要大改 CSS）。\n\n"
            f"字幕示例文本：{cue_text}\n说话人：{speaker_name or '（无）'}\n\n"
            f"用户修改要求：{ask}\n\n"
            f"当前主题原文：\n{sections_of(original)}"
        )
        from .web_theme_compiler import REPAIR_SYSTEM
        from .design_guidance import load_design_guidance
        guidance,receipt=load_design_guidance(str(original.get('concept',''))+' '+ask)
        trace['design_skills']=receipt
        system_prompt=REPAIR_SYSTEM
        output_tokens=8192
        if original.get('motionSpec'):
            # A complete authored revision has the same source size/reasoning
            # needs as one generated candidate, even on the animation path.
            from .theme_generation_policy import authored_request_budget
            output_tokens,_=authored_request_budget(selection.provider,models,candidate_count=1)
        if art_revision:
            from .caption_material_direction import MATERIAL_DIRECTION,MOTION_DELIVERY,TEXT_EMPHASIS_DELIVERY
            from .theme_generation_policy import authored_request_budget
            output_tokens,limits=authored_request_budget(selection.provider,models,candidate_count=1)
            if deadline_seconds is None:budget=limits.concepts
            system_prompt=('对当前字幕制作保留结构和动作的材质版本。保留HTML、构图比例和MotionSpec，协调字体、颜色、框面、边缘、纹理与阴影。'
                '原始正文和时序归宿主，保留主题身份与明确用户锁；程序默认字体不冻结。只输出完整原格式分节，含APPEARANCE和MOTION_SPEC。'
                '不添加台词、口号、脚本或网络资源。\n'+MOTION_DELIVERY+'\n'+TEXT_EMPHASIS_DELIVERY)
            user_prompt=('为实际字幕“'+cue_text+'”增强材质与层次，保留原框体、角色和完整动作。'
                '保留完整框体、角色与认可动作，增强材质层次。\n修改要求：'+ask+
                '\n共同构图建议：'+json.dumps(MATERIAL_DIRECTION,ensure_ascii=False)+'\n'+guidance+
                '\n改前完整主题：\n'+sections_of(original))
        if not art_revision:
            # Directed animation repair must receive the same current art
            # decisions as generation without freezing its defective tracks.
            from .caption_material_direction import MOTION_DELIVERY
            user_prompt+='\n'+guidance+'\n'+MOTION_DELIVERY
        user_prompt+='\n'+PRESERVATION_DIRECTION
        if art_revision:user_prompt+='\n'+SURFACE_DIRECTION
        user_prompt+='\n必须保留的手工修改与用户锁：'+json.dumps(constraints,ensure_ascii=False)
        # Text-only providers receive observations as text, never hidden image
        # attachments or a silent switch to another generation model.
        from .provider_service import GLOBAL_PROVIDER_SERVICE
        capabilities=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish').capabilities()
        image_frames=reference_frames if capabilities.vision else ()
        trace['reference_pixels_attached']=bool(image_frames)
        trace['request_prompt']=user_prompt

        def beat() -> None:
            flow_state["last_beat"] = time.monotonic()

        def guarded_cancel() -> bool:
            if time.monotonic()-started >= budget:
                return True
            if cancel_check is not None and cancel_check():
                return True
            if time.monotonic() - flow_state["last_beat"] > stall_deadline_seconds:
                flow_state["stall_triggered"] = True
                progress("STALL_TIMEOUT")
                return True
            return False

        def parse_theme_payload(text: str) -> dict[str, Any]:
            from .theme_metadata import parse_theme_input
            return parse_theme_input(text)

        attempt_prompt = user_prompt
        last_error = ""
        for _attempt in (1,):
            if guarded_cancel():
                if flow_state["stall_triggered"]:
                    raise AIProviderError(
                        "Provider 超过 "
                        f"{stall_deadline_seconds:.0f} 秒无输出（疑似挂起），已自动中止。",
                        category="timeout",
                    )
                raise AIProviderError("主题修改已取消。", category="cancelled")
            if last_error:
                attempt_prompt = (
                    f"{user_prompt}\n\n你上一版输出被拒收，唯一原因：{last_error}\n"
                    "请只修复这一个具体问题，逐字保留上一版的全部创意、场景物件与动画"
                    "（CONCEPT 点名的每个物件一个都不能删），千万不要因此简化或保守化；"
                    "仍按十个 ===分节=== 格式输出完整主题（含 ===APPEARANCE===）。"
                )
            progress("REQUESTING")
            beat()
            output_stats = {"chars": 0, "buffer": [], "last_flush": 0.0, "last_note": 0.0}

            def flush_stream_buffer(force: bool = False) -> None:
                if on_stream_text is None:
                    return
                now = time.monotonic()
                if not force and now - output_stats["last_flush"] < 0.25:
                    return
                if output_stats["buffer"]:
                    chunk = "".join(output_stats["buffer"])
                    output_stats["buffer"] = []
                    output_stats["last_flush"] = now
                    try:
                        on_stream_text(chunk)
                    except Exception:
                        pass

            def on_stream_event(kind: str, detail: str) -> None:
                now = time.monotonic()
                beat()
                if kind == "thinking":
                    if now - output_stats["last_note"] > 1.2:
                        output_stats["last_note"] = now
                        progress("模型思考修改方案…")
                    return
                if kind == "delta":
                    output_stats["chars"] += len(detail)
                    output_stats["buffer"].append(detail)
                    flush_stream_buffer()
                    if now - output_stats["last_note"] > 1.0:
                        output_stats["last_note"] = now
                        progress(f"正在输出修改后的主题（{output_stats['chars'] // 100} 百字）…")
                    return
                if kind == "stderr":
                    if now - output_stats["last_note"] > 2.0:
                        output_stats["last_note"] = now
                        progress(f"CLI 输出：{detail[-120:]}")

            # The shared provider owns file/stdin transport and model budgets.
            response_text = provider.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": ([{'type':'text','text':attempt_prompt}]+[
                        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+__import__('base64').b64encode(Path(frame).read_bytes()).decode('ascii')}}
                        for frame in image_frames]) if image_frames else attempt_prompt},
                ],
                max_tokens=output_tokens,
                temperature=0.4,
                timeout=max(.1,budget-(time.monotonic()-started)),
                cancel_check=guarded_cancel,
                stage="studio_web_theme_refine",
                on_stream_event=on_stream_event,
            )
            flush_stream_buffer(force=True)
            trace["raw_provider_responses"].append({"response_text": str(response_text)})
            progress("VALIDATING")
            try:
                from .theme_metadata import recover_generated_names
                from .caption_creative_pipeline import METADATA_REPAIR_SCHEMA
                def repair_metadata(fields):
                    return provider.complete([{'role':'user','content':'只补全主题名称，输出 {"names":[{"path":"原path","name":"简短名称"}]}。禁止修改任何视觉内容。'+json.dumps(fields,ensure_ascii=False)}],
                        max_tokens=600,timeout=min(25.,max(.1,budget-(time.monotonic()-started))),
                        json_schema=METADATA_REPAIR_SCHEMA,cancel_check=guarded_cancel,stage='studio_web_theme_name_repair')
                parsed=parse_theme_payload(response_text)
                parsed['id']=original['id']
                # Restore protected sections before validating the echoed
                # markup. Only the retained artwork can reach the renderer.
                parsed,restored=enforce_constraints(parsed,constraints)
                trace['restored_user_intent']=restored
                if art_revision:
                    from .theme_design_preservation import resolve_appearance_references
                    parsed,retained=resolve_appearance_references(parsed,original)
                    trace['retained_appearance_references']=retained
                parsed=recover_generated_names({'webTheme':parsed},
                    request_id=original['id'],repair=repair_metadata,cancel_check=guarded_cancel,
                    event=lambda event,fields:trace.setdefault('metadata_events',[]).append(dict(event=event,**fields)))['webTheme']
                if art_revision:validate_surface_revision(original,parsed)
                _document = WebThemeDocument.from_dict(parsed)
                if original.get('motionSpec') and not _document.motion_spec:
                    raise WebThemeValidationError('修改不得丢失原GSAP MotionSpec')
                from .web_theme import validate_generated_theme

                if art_revision:
                    from .web_theme import validate_preserved_theme_revision
                    validate_preserved_theme_revision(_document,original)
                elif original.get('motionSpec'):
                    from .web_theme import validate_existing_authored_revision
                    validate_existing_authored_revision(_document)
                else:validate_generated_theme(_document, instruction=ask,design_version=design_version)
                refined = _document.to_dict()
                trace["validation_errors"] = []
                break
            except (WebThemeValidationError, ValueError) as exc:
                last_error = str(exc)
                trace["validation_errors"].append(last_error)
                refined = None
        if refined is None:
            raise AIProviderError(
                f"修改后的主题未通过契约校验：{last_error[:200]}",
                category="schema_validation",
            )
        message = "主题已按修改要求更新。"
        trace["web_theme_source"] = "refined"
    except BaseException as exc:  # noqa: BLE001 - refine must never destroy the draft
        category = str(getattr(exc, "category", "")) or ""
        if category == "cancelled" and not flow_state.get("stall_triggered"):
            trace["web_theme_source"] = "cancelled"
            trace["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:400]
            _persist_ai_design_trace(trace)
            raise
        refined = original
        headline, _detail, hint, _action = _provider_failure_message(exc)
        if flow_state.get("stall_triggered"):
            message = (
                f"Provider 超过 {stall_deadline_seconds:.0f} 秒无输出（疑似挂起或认证失败），"
                "已自动中止并保留原主题。"
            )
        else:
            message = f"{headline or 'AI 修改失败'}，已保留原主题。{hint}".strip()
        trace["web_theme_source"] = "refine_failed"
        trace["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:400]
    trace["provider"] = {
        "provider": provider_name,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    trace["theme_name"] = str((refined or {}).get("name") or "")
    from .motion_spec_repair import changed_paths
    from .theme_draft import canonical_theme
    trace['after_theme']=refined
    trace['before_hash']=hashlib.sha256(canonical_theme(original).encode('utf8')).hexdigest()
    trace['after_hash']=hashlib.sha256(canonical_theme(refined or original).encode('utf8')).hexdigest()
    trace['changed_paths']=changed_paths(original,refined or original)
    trace_path = _persist_ai_design_trace(trace)
    return AIWebThemeSuggestion(
        theme=refined or original,
        source=str(trace.get("web_theme_source") or "refined"),
        message=message,
        trace_path=trace_path,
        provider=provider_name,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
